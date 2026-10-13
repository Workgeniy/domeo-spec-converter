import base64
import io

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill

from app.export.excel import build_workbook
from app.models import ExportRequest, KpSettings, SummaryItem
from .conftest import sample


def encoded(wb):
    buffer = io.BytesIO()
    wb.save(buffer)
    return base64.b64encode(buffer.getvalue()).decode()


def template():
    wb = Workbook()
    ws = wb.active
    ws.title = 'Моя форма'
    ws.merge_cells('A1:E1')
    ws['A1'] = 'КП {{contract_number}} — {{title}}'
    ws.append(['Наименование', 'Количество', 'Цена за ед. товара, с НДС', 'Стоимость товара, с НДС', 'Ставка НДС'])
    ws.append(['Старый товар', 123, 999, '=B3*C3', .2])
    ws.append(['Всего', None, None, '=SUM(D3:D3)'])
    ws.append(['Подписи: {{supplier_position}}'])
    ws.merge_cells('A5:E5')
    ws['A3'].font = Font(name='Arial', size=14, color='CC0000')
    ws['C3'].fill = PatternFill('solid', fgColor='FFFF00')
    ws.column_dimensions['A'].width = 45
    ws.column_dimensions['E'].hidden = True
    ws.page_setup.orientation = 'portrait'
    ws.page_setup.paperSize = 9
    ws.print_area = 'A1:E5'
    ws.print_title_rows = '1:2'
    wb.create_sheet('Условия')['A1'] = 'Доставка по договору'
    return wb


def request(wb, n=2):
    return ExportRequest(file_name='object.xlsx', title='Школа', kp=KpSettings(contract_number='42', supplier_position='Директор'),
                         summary=[SummaryItem(name=f'Стол {i}', qty=2, price=100, installation=False) for i in range(n)],
                         kp_template=encoded(wb))


def test_custom_template_preserves_layout_and_moves_footer():
    wb = build_workbook(request(template()))
    ws = wb['Моя форма']
    assert wb.sheetnames == ['Моя форма', 'Условия']
    assert ws['A1'].value == 'КП 42 — Школа'
    assert [ws.cell(r, 1).value for r in (3, 4)] == ['Стол 0', 'Стол 1']
    assert ws['C3'].value == 100
    assert ws['D4'].value == '=B4*C4'
    assert ws['D5'].value == '=SUM(D3:D4)'
    assert ws['A6'].value == 'Подписи: Директор'
    assert 'A6:E6' in str(ws.merged_cells)
    assert ws['A3'].font.name == 'Arial' and ws['A4'].font.size == 14
    assert ws['C4'].fill.fgColor.rgb == '00FFFF00'
    assert ws.column_dimensions['A'].width == 45 and ws.column_dimensions['E'].hidden
    assert ws.page_setup.orientation == 'portrait' and ws.print_title_rows == '$1:$2'
    assert str(ws.print_area) == "'Моя форма'!$A$1:$E$6"
    assert wb['Условия']['A1'].value == 'Доставка по договору'
    buffer = io.BytesIO()
    wb.save(buffer)
    assert load_workbook(io.BytesIO(buffer.getvalue()))['Моя форма']['D5'].value == '=SUM(D3:D4)'


def test_price_without_vat_works_when_template_has_no_vat_column():
    wb = template()
    wb.active['E2'] = 'Цена за ед. без НДС'
    result = build_workbook(request(wb))
    assert result.active['E3'].value == pytest.approx(100 / 1.22)


def test_single_table_includes_installation_in_price_when_no_smr_column():
    data = request(template())
    data.summary[0].installation = True
    data.kp.installation_percent = 10
    output = build_workbook(data)
    assert output.active['C3'].value == 110 and output.active['C4'].value == 100


@pytest.mark.parametrize('n', [0, 1, 4])
def test_template_empty_and_growing_table(n):
    wb = build_workbook(request(template(), n))
    total = 3 + max(1, n)
    assert wb.active.cell(total, 1).value == 'Всего'
    assert wb.active.cell(total + 1, 1).value == 'Подписи: Директор'
    if n == 0:
        assert wb.active['A3'].value is None and wb.active['D3'].value is None


def test_customer_template_preserves_original_headers_and_signatures():
    original = load_workbook(sample('Приложение.xlsx'))
    data = request(original)
    data.summary[0].installation = True
    output = build_workbook(data)
    assert output.sheetnames == original.sheetnames
    for name in ('1', '2'):
        assert output[name]['B2'].value == original[name]['B2'].value
        assert output[name].column_dimensions['B'].width == original[name].column_dimensions['B'].width
        assert output[name].page_setup == original[name].page_setup
    assert output['1']['C4'].value == 'Стол 0' and output['2']['C4'].value == 'Стол 1'
    assert output['1']['N5'].value == '=SUM(N4:N4)'
    assert output['2']['L5'].value == '=SUM(L4:L4)'


def test_invalid_template_is_rejected():
    with pytest.raises(ValueError, match='XLSX'):
        build_workbook(ExportRequest(kp=KpSettings(), kp_template='broken'))
    wb = template()
    wb.active['A4'] = 'Без итога'
    with pytest.raises(ValueError, match='Итого'):
        build_workbook(request(wb))


def test_auxiliary_quantity_sheet_does_not_block_template():
    wb = template()
    detail = wb.create_sheet('Детализация')
    detail.append(['Наименование', 'Количество'])
    detail.append(['Стол 0', 2])
    output = build_workbook(request(wb))
    assert output['Моя форма']['C3'].value == 100
    assert output['Детализация']['A2'].value == 'Стол 0'


def test_template_export_api_returns_workbook_and_validation_error():
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    response = client.post('/api/export', json=request(template()).model_dump())
    assert response.status_code == 200
    assert load_workbook(io.BytesIO(response.content)).active['A3'].value == 'Стол 0'
    response = client.post('/api/export', json={'kp': {}, 'kp_template': 'broken'})
    assert response.status_code == 422 and 'XLSX' in response.json()['detail']


def test_custom_template_target_margin_and_saved_indexation():
    from app.models import Indexation
    data = request(template(), 1)
    data.kp.margin_percent = 20
    data.kp.markup_percent = 90
    data.indexation = Indexation(date='2021-01-01', base_date='2020-01-01', rates={'': 10}, apply_to_kp=True)
    result = build_workbook(data)
    # Сохранённая дата расчёта в прошлом: текущая дата не меняет цену архивного КП.
    assert result.active['C3'].value == 137.53
