from app.services import calculate_fee

def test_fee_first_hour(): assert calculate_fee(60) == 20

def test_fee_over_one_hour(): assert calculate_fee(61) == 30

def test_fee_two_hours(): assert calculate_fee(120) == 30
