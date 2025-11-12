from math import ceil


def compute_fee_minutes(elapsed_minutes: int) -> int:
    """
    Pricing rules:
    - First 10 minutes free
    - Every additional 30 minutes (or part thereof) -> PKR 100
    - Max daily cap PKR 800
    """
    free = 10
    if elapsed_minutes <= free:
        return 0
    chargeable = elapsed_minutes - free
    blocks = ceil(chargeable / 30)
    fee = blocks * 100
    return min(fee, 800)
