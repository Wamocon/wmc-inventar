import openpyxl
wb = openpyxl.load_workbook('docs/vorlagen/bestandsliste_anonymisiert.xlsx', read_only=True, data_only=True)
print('sheets:', [(ws.title, ws.max_row, ws.max_column) for ws in wb.worksheets])
ws = wb['Inventar']
print('--- rows 1-6, cols 1-16 ---')
for r in range(1, 7):
    vals = [ws.cell(row=r, column=c).value for c in range(1, 17)]
    print(r, vals)
print('--- rows 118-122 ---')
for r in range(118, 123):
    print(r, [ws.cell(row=r, column=c).value for c in range(1, 17)])
