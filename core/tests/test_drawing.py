import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.parsing.drawing import drawing_text


def plan():
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 50), '1.1')
    page.insert_text((150, 150), '2.10 = 6')
    page.set_rotation(90)
    doc.new_page()  # Скан/пустая страница — не считать проверенной.
    return doc.tobytes()


def test_text_and_rotated_coordinates_without_ocr():
    result = drawing_text(plan(), [1, 2, 1])
    assert len(result['pages']) == 2
    lines = result['pages'][0]['lines']
    assert [line['text'] for line in lines] == ['1.1', '2.10 = 6']
    assert lines[0]['x'] > 700 and lines[0]['y'] == 50
    assert result['pages'][1]['skipped_reason']


def test_specification_page_is_skipped(synthetic_spec_pdf):
    assert 'спецификации' in drawing_text(synthetic_spec_pdf.read_bytes(), [1])['pages'][0]['skipped_reason']


@pytest.mark.parametrize('pages', [[], [0], [3], list(range(1, 22))])
def test_bad_page_selection(pages):
    with pytest.raises(ValueError):
        drawing_text(plan(), pages)


def test_endpoint_and_invalid_pdf():
    client = TestClient(app)
    response = client.post('/api/drawing-text', files={'file': ('plan.pdf', plan())}, data={'pages': '1,2'})
    assert response.status_code == 200 and len(response.json()['pages']) == 2
    response = client.post('/api/drawing-text', files={'file': ('plan.pdf', b'bad')}, data={'pages': '1'})
    assert response.status_code == 422
