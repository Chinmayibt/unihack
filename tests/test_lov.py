from app.services.standards import canonical_lov_key
from app.services.value_normalize import resolve_lov


CUT_OFF = "Abrasives>Cutting Products>Cut-Off Discs"


def test_canonical_lov_key_folds_case_space_and_unicode():
    assert canonical_lov_key("Aluminum Oxide") == canonical_lov_key("aluminum oxide")
    assert canonical_lov_key("Aluminum Oxide") == canonical_lov_key(" ALUMINUM   OXIDE ")
    assert canonical_lov_key("Aluminum Oxide") == canonical_lov_key("Aluminum\u00a0Oxide")
    assert canonical_lov_key("Cut-Off Discs") == canonical_lov_key("Cut Off Discs")


def test_resolve_lov_accepts_canonical_and_case_variants():
    assert resolve_lov("Material", "Aluminum Oxide") == ("Aluminum Oxide", "LOV")
    assert resolve_lov("Material", "aluminum oxide") == ("Aluminum Oxide", "LOV")
    assert resolve_lov("Material", "ALUMINUM  OXIDE") == ("Aluminum Oxide", "LOV")
    assert resolve_lov("Abrasive Material", "Silicon Carbide") == ("Silicon Carbide", "LOV")
    assert resolve_lov("Abrasive Material", "silicon carbide") == ("Silicon Carbide", "LOV")


def test_resolve_lov_uses_approved_aliases_only():
    assert resolve_lov("Material", "aluminum oxide grain") == ("Aluminum Oxide", "LOV")
    assert resolve_lov("Material", "ceramic blend") == ("Ceramic", "LOV")
    assert resolve_lov("Material", "premium ceramic blend") == ("Ceramic", "LOV")
    assert resolve_lov("Abrasive Material", "ceramic grain blend") == ("Ceramic", "LOV")
    assert resolve_lov("Abrasive Material", "premium ceramic grain blend") == ("Ceramic", "LOV")
    assert resolve_lov("Product Type", "Metal Cut Off Wheel", CUT_OFF) == (
        "Cut-Off Discs",
        "LOV",
    )
    assert resolve_lov("Product Type", "Cut-Off & Grinding Discs", CUT_OFF) == (
        "Cut-Off Discs",
        "LOV",
    )
    assert resolve_lov("Product Type", "Masonry Cut Off Wheel", CUT_OFF) == (
        "Cut-Off Discs",
        "LOV",
    )
    assert resolve_lov("Product Type", "Cut Off Discs", CUT_OFF) == ("Cut-Off Discs", "LOV")


def test_resolve_lov_does_not_alias_unsupported_semantics():
    assert resolve_lov("Abrasive Material", "zirconia") == (None, None)
    assert resolve_lov("Abrasive Material", "zirconia grain") == (None, None)
    assert resolve_lov("Material", "Bonded Abrasive") == (None, None)
    assert resolve_lov("Material", "metal") == (None, None)
    assert resolve_lov("Product Type", "Type 1", CUT_OFF) == (None, None)
