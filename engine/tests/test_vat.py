"""Tests for the 9-box VAT return computation."""

from __future__ import annotations

from ledgerline_engine.money import Money
from ledgerline_engine.vat import (
    VatDirection,
    VatEntry,
    compute_vat_return,
)


def _gbp(minor: int) -> Money:
    return Money(minor, "GBP")


def _sale(net: int, vat: int, *, ec: bool = False) -> VatEntry:
    return VatEntry(direction=VatDirection.SALE, net=_gbp(net), vat=_gbp(vat), is_ec=ec)


def _purchase(net: int, vat: int, *, ec: bool = False) -> VatEntry:
    return VatEntry(direction=VatDirection.PURCHASE, net=_gbp(net), vat=_gbp(vat), is_ec=ec)


def test_simple_sales_and_purchases() -> None:
    # Sales net 1000.00 / VAT 200.00; purchases net 500.00 / VAT 100.00.
    result = compute_vat_return([_sale(100000, 20000), _purchase(50000, 10000)])
    assert result.box1_minor == 20000  # output VAT
    assert result.box2_minor == 0  # no EC acquisitions
    assert result.box3_minor == 20000  # box1 + box2
    assert result.box4_minor == 10000  # input VAT
    assert result.box5_minor == 10000  # |box3 - box4| = 100.00 to pay
    assert result.box6_minor == 100000  # sales ex VAT
    assert result.box7_minor == 50000  # purchases ex VAT
    assert result.box8_minor == 0
    assert result.box9_minor == 0


def test_box3_equals_box1_plus_box2() -> None:
    result = compute_vat_return([_sale(100000, 20000), _purchase(50000, 10000, ec=True)])
    assert result.box2_minor == 10000  # EC acquisition VAT
    assert result.box3_minor == result.box1_minor + result.box2_minor


def test_box5_is_absolute_difference() -> None:
    # Reclaim position: input VAT exceeds output VAT.
    result = compute_vat_return([_sale(10000, 2000), _purchase(100000, 20000)])
    # box3 = 2000, box4 = 20000 -> box5 = |2000 - 20000| = 18000 to reclaim.
    assert result.box5_minor == 18000


def test_ec_supplies_and_acquisitions_in_boxes_8_and_9() -> None:
    result = compute_vat_return(
        [_sale(40000, 0, ec=True), _purchase(30000, 6000, ec=True)]
    )
    assert result.box8_minor == 40000  # EC sales (goods) ex VAT
    assert result.box9_minor == 30000  # EC acquisitions ex VAT


def test_empty_return_is_all_zero() -> None:
    result = compute_vat_return([])
    assert (result.box1_minor, result.box3_minor, result.box5_minor, result.box6_minor) == (
        0,
        0,
        0,
        0,
    )


def test_public_api_exposes_vat() -> None:
    from ledgerline_engine import api

    result = api.compute_vat_return([
        api.VatEntry(direction=api.VatDirection.SALE, net=_gbp(100000), vat=_gbp(20000)),
    ])
    assert isinstance(result, api.VatReturn)
    assert result.box1_minor == 20000
