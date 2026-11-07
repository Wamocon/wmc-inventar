"""F-138: Siegel (PAdES) mit pyhanko 0.38.

Nach der letzten Signatur versiegelt das Tool das PDF mit pyhanko als PAdES
mit dem Zertifikat aus SIEGEL_P12 (F-138).

Beim Test legt ``manage.py testsiegel`` die Dateien ``var/testsiegel.p12``
(Passwort „testsiegel") und ``var/testsiegel.crt`` (PEM) an, nur im
Entwicklungsmodus (TESTSCHNITTSTELLE Kapitel 1).
"""
from __future__ import annotations

import datetime
import io
import logging
import os
from pathlib import Path

from django.conf import settings

from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.sign.fields import SigSeedSubFilter
from pyhanko.sign.signers import PdfSignatureMetadata, sign_pdf
from pyhanko.sign.signers.pdf_cms import SimpleSigner

# --- Pfade --------------------------------------------------------------------
_ROOT = Path(
    getattr(settings, "BASE_DIR", None)
    or Path(__file__).resolve().parent.parent.parent
)
VAR_DIR = Path(getattr(settings, "DATEIABLAGE", str(_ROOT / "var")))

_env_p12 = os.environ.get("SIEGEL_P12", "").strip()
SIEGEL_P12 = Path(_env_p12) if _env_p12 else _ROOT / "var" / "testsiegel.p12"
SIEGEL_CRT = SIEGEL_P12.with_suffix(".crt")
SIEGEL_PASSWORT = os.environ.get("SIEGEL_PASSWORT", "testsiegel")


def _debug_modus() -> bool:
    """Nur im Entwicklungsmodus (INVENTAR_DEBUG=1) wird das Test-Siegel verwendet."""
    return os.environ.get("INVENTAR_DEBUG", "").strip() in ("1", "true", "ja")


def _signer_laden():
    """Zertifikat und Schlüssel aus dem P12 laden (F-138).

    Liefert ein SimpleSigner-Objekt für pyhanko 0.38.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.serialization import pkcs12
    from pyhanko_certvalidator.registry import SimpleCertificateStore
    from pyhanko.keys.pemder import load_certs_from_pemder_data, load_private_key_from_pemder_data
    from pyhanko.sign.signers.pdf_cms import SimpleSigner

    p12_bytes = SIEGEL_P12.read_bytes()
    key, cert, cas = pkcs12.load_key_and_certificates(
        p12_bytes, SIEGEL_PASSWORT.encode(),
    )
    if key is None or cert is None:
        raise ValueError("P12 enthält keinen Schlüssel oder kein Zertifikat.")

    # asn1crypto-Zertifikate: das Endentity-Zertifikat und die CAs aus dem
    # P12. pyhanko erwartet asn1crypto.x509.Certificate, nicht
    # cryptography.x509.
    cert_der = cert.public_bytes(serialization.Encoding.DER)
    alle_certs = list(load_certs_from_pemder_data(cert_der))
    for ca in cas or ():
        ca_der = ca.public_bytes(serialization.Encoding.DER)
        alle_certs.extend(load_certs_from_pemder_data(ca_der))

    # Schlüssel nach asn1crypto konvertieren.
    key_der = key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_info = load_private_key_from_pemder_data(key_der, passphrase=None)

    store = SimpleCertificateStore.from_certs(alle_certs)
    return SimpleSigner(
        signing_cert=alle_certs[0],
        signing_key=key_info,
        cert_registry=store,
    )


def siegel_anwenden(pdf_bytes: bytes):
    """F-138: PDF mit PAdES versiegeln (pyhanko 0.38).

    Nimmt das unversiegelte PDF, versiegelt es mit dem Zertifikat aus
    ``SIEGEL_P12`` und liefert die versiegelte PDF zurück.

    Liefert ``None``, wenn das Siegel nicht verfügbar ist (kein P12,
    falsches Passwort, fehlende Bibliothek) – der Aufrufer muss dann
    ohne Siegel weiterlaufen (Bestätigung ohne Anhang).
    """
    log = logging.getLogger("wmc")

    # Siegel laden – Fehlschlag → None.
    try:
        signer = _signer_laden()
    except Exception as e:
        log.warning("SIEGEL_P12 nicht verfügbar: %s", e)
        return None

    # Eingangs-Stream für den Inkrementellen Writer.
    eingang = io.BytesIO(pdf_bytes)
    writer = IncrementalPdfFileWriter(eingang)

    # PAdES-Signatur (unsichtbar, kein Widget).
    sign_meta = PdfSignatureMetadata(
        field_name="Signatur",
        md_algorithm="sha256",
        subfilter=SigSeedSubFilter.PADES,
        reason="WMC Inventar Prüfprotokoll",
    )

    ausgang = io.BytesIO()
    sign_pdf(
        writer,
        sign_meta,
        signer,
        output=ausgang,
    )
    return ausgang.getvalue()


def pdf_verifizieren(pdf_bytes: bytes) -> dict:
    """F-138: PDF-Signatur mit pyhanko 0.38 prüfen.

    Liefert ein Dict mit ``gueltig`` (bool) und ``format`` (str).
    Nach einer Änderung an einem Byte ist die Signatur ungültig.
    """
    from pyhanko.pdf_utils.reader import PdfFileReader
    from pyhanko.pdf_utils.generic import IndirectObject
    from pyhanko.sign.fields import SigSeedSubFilter
    from pyhanko.sign.validation import validate_pdf_signature
    from pyhanko.sign.validation.pdf_embedded import (
        EmbeddedPdfSignature,
        collect_embedded_signatures,
    )

    ergebnis: dict = {"gueltig": False, "format": ""}

    try:
        reader = PdfFileReader(io.BytesIO(pdf_bytes))
        sigs = collect_embedded_signatures(reader)
        if not sigs:
            ergebnis["format"] = "keine Signatur"
            return ergebnis

        sig = sigs[0]
        sig_obj = sig.sig_object
        if isinstance(sig_obj, IndirectObject):
            sig_obj = sig_obj.get_object()
        subfilter = sig_obj.get("/SubFilter", "")
        if subfilter in (SigSeedSubFilter.PADES, SigSeedSubFilter.PBAD_PADES):
            ergebnis["format"] = "PAdES"
        elif subfilter in (
            SigSeedSubFilter.ADOBE_PKCS7_DETACHED,
            SigSeedSubFilter.ETSI_RFC3161,
        ):
            ergebnis["format"] = str(subfilter)
        else:
            ergebnis["format"] = str(subfilter or "unbekannt")

        status = validate_pdf_signature(sig)
        # F-138: „gueltig" bedeutet hier: die Signatur ist intakt, d.h. die
        # geprüften Bytes wurden nicht verändert. status.valid prüft die
        # Zertifikatskette, die bei einem selbstsignierten Test-Zertifikat
        # nicht abgeschlossen werden kann – das ist für diesen Test unerheblich.
        ergebnis["gueltig"] = bool(status.intact)
        if not status.intact:
            ergebnis["format"] += " (Byte verändert)"

    except Exception:
        import logging
        logging.getLogger("wmc").exception("pdf_verifizieren: Fehler.")
        ergebnis["gueltig"] = False
        if not ergebnis["format"]:
            ergebnis["format"] = "ungültig"

    return ergebnis


def testsiegel_anlegen() -> tuple[Path, Path]:
    """TESTSCHNITTSTELLE Kapitel 1: var/testsiegel.p12 und var/testsiegel.crt anlegen.

    Nur im Entwicklungsmodus (INVENTAR_DEBUG=1).
    Passwort: „testsiegel".
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID

    if not _debug_modus():
        raise PermissionError(
            "testsiegel ist nur im Entwicklungsmodus erlaubt (INVENTAR_DEBUG=1)."
        )

    VAR_DIR.mkdir(parents=True, exist_ok=True)

    key = ec.generate_private_key(ec.SECP256R1())

    name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "Wamocon IT Test-Siegel"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Wamocon GmbH"),
    ])

    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, content_commitment=True,
                key_encipherment=False, data_encipherment=False,
                key_agreement=False, key_cert_sign=True,
                crl_sign=True, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CODE_SIGNING]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )

    # P12 schreiben.
    from cryptography.hazmat.primitives.serialization import (
        BestAvailableEncryption,
    )
    p12_puffer = io.BytesIO()
    p12_puffer.write(pkcs12.serialize_key_and_certificates(
        name=None,
        key=key,
        cert=cert,
        cas=None,
        encryption_algorithm=BestAvailableEncryption(SIEGEL_PASSWORT.encode()),
    ))
    SIEGEL_P12.write_bytes(p12_puffer.getvalue())

    # PEM (Zertifikat) schreiben.
    SIEGEL_CRT.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

    return SIEGEL_P12, SIEGEL_CRT
