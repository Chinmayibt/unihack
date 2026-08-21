from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.product import ProductStatus


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


class RawProduct(BaseModel):
    """Strict contract for one CSV row. Does not decide canonical brand."""

    model_config = ConfigDict(populate_by_name=True)

    index: int | None = None
    mfg_part_num: str = Field(alias="Mfg_Part_Num")
    part_desc: str = Field(alias="Part_Desc")
    e1_brand: str | None = Field(default=None, alias="E1_Brand")
    unilog_brand: str | None = Field(default=None, alias="Unilog_Brand")
    dib_brand: str | None = Field(default=None, alias="DIB_Brand")
    part_manuf: str | None = Field(default=None, alias="Part_Manuf")

    @field_validator("mfg_part_num", "part_desc", mode="before")
    @classmethod
    def required_text(cls, value: object) -> str:
        if value is None or str(value).strip() == "":
            raise ValueError("is missing")
        return str(value).strip()

    @field_validator("e1_brand", "unilog_brand", "dib_brand", "part_manuf", mode="before")
    @classmethod
    def optional_text(cls, value: object) -> str | None:
        if value is None:
            return None
        return _blank_to_none(str(value))


class Product(BaseModel):
    """Phase 1 internal product object. Source values are preserved as-is."""

    source_index: int
    mpn: str
    description: str
    e1_brand: str | None = None
    unilog_brand: str | None = None
    dib_brand: str | None = None
    manufacturer: str | None = None
    status: ProductStatus = ProductStatus.INGESTED


class RowError(BaseModel):
    row: int
    error: str


class IngestionStats(BaseModel):
    total_rows: int = 0
    valid_rows: int = 0
    invalid_rows: int = 0
    missing_mpn: int = 0
    missing_description: int = 0
    duplicate_mpns: int = 0
    missing_manufacturer: int = 0
    missing_brand: int = 0


class UploadResponse(BaseModel):
    status: str
    job_id: str
    total_rows: int
    valid_rows: int
    invalid_rows: int
    missing_mpn: int = 0
    missing_description: int = 0
    duplicate_mpns: int = 0
    missing_manufacturer: int = 0
    missing_brand: int = 0
    errors: list[RowError] = []
    product_ids: list[int] = Field(default_factory=list)


class ProductIntakeItem(BaseModel):
    """Friendly JSON intake for one product (aliases map to CSV columns)."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    mpn: str | None = Field(default=None, alias="Mfg_Part_Num")
    description: str | None = Field(default=None, alias="Part_Desc")
    e1_brand: str | None = Field(default=None, alias="E1_Brand")
    unilog_brand: str | None = Field(default=None, alias="Unilog_Brand")
    dib_brand: str | None = Field(default=None, alias="DIB_Brand")
    manufacturer: str | None = Field(default=None, alias="Part_Manuf")
    index: int | None = None

    def to_csv_row(self) -> dict:
        return {
            "index": self.index,
            "Mfg_Part_Num": self.mpn,
            "Part_Desc": self.description,
            "E1_Brand": self.e1_brand,
            "Unilog_Brand": self.unilog_brand,
            "DIB_Brand": self.dib_brand,
            "Part_Manuf": self.manufacturer,
        }


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_index: int
    mpn: str
    description: str
    e1_brand: str | None = None
    unilog_brand: str | None = None
    dib_brand: str | None = None
    manufacturer: str | None = None
    status: str
