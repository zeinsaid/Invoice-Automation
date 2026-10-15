from invoice_automation.layout import clean_text, ean_is_valid, normalise_barcode, parse_number


def test_parse_number_formats():
    assert parse_number("23.60") == 23.60
    assert parse_number("-11.80") == -11.80
    assert parse_number("2,51249") == 2.51249  # comma decimal (Jumbo)
    assert parse_number("1,234.50") == 1234.50  # thousands separator
    assert parse_number("5 774") == 5.774  # dot read as a space (Cosmos)
    assert parse_number("19 %") == 19
    assert parse_number("") is None
    assert parse_number("abc") is None


def test_clean_text_removes_checkbox_marks():
    assert clean_text("KINDER CRISPY 170GR\n:selected:") == "KINDER CRISPY 170GR"


def test_ean_check_digit():
    assert ean_is_valid("5449000000439")  # EAN-13
    assert ean_is_valid("80052357")  # EAN-8
    assert not ean_is_valid("5449000000438")  # one digit off
    assert not ean_is_valid("12345")


def test_normalise_barcode():
    assert normalise_barcode("40331423-n") == "40331423"  # Cosmos suffix
    assert normalise_barcode("52130036125 44") == "5213003612544"  # wrapped onto two lines
    assert normalise_barcode("52018251n 1623") == "52018251"  # handwritten item code next to it
    assert normalise_barcode("") == ""
