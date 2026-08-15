from app.schemas.product import Product, RawProduct


def normalize_raw_product(raw: RawProduct, source_index: int) -> Product:
    """Convert a validated CSV row into the Phase 1 internal Product.

    Brand placeholders such as "-- Unbranded --" are preserved. Canonical
    brand resolution belongs to a later phase.
    """
    return Product(
        source_index=source_index,
        mpn=raw.mfg_part_num,
        description=raw.part_desc,
        e1_brand=raw.e1_brand,
        unilog_brand=raw.unilog_brand,
        dib_brand=raw.dib_brand,
        manufacturer=raw.part_manuf,
    )
