from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.connection import get_db
from app.database.models import ProductRecord
from app.schemas.final_output import FinalProductEnvelope, OutputGenerateResponse
from app.services.output_assemble import assemble_output
from app.services.output_generate import generate_output

router = APIRouter(tags=["output"])


@router.get("/products/{product_id}/output", response_model=FinalProductEnvelope)
def read_product_output(product_id: int, db: Session = Depends(get_db)) -> FinalProductEnvelope:
    product = db.get(ProductRecord, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found")
    try:
        return assemble_output(product_id, db)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/output/generate", response_model=OutputGenerateResponse)
def generate_delivery_output(db: Session = Depends(get_db)) -> OutputGenerateResponse:
    result = generate_output(db)
    return result
