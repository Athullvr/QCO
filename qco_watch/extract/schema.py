"""Strict extraction schema. Every fact carries page + verbatim quote. Unknown = null / empty list."""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ChangeType = Literal["new", "amended", "extended", "relaxed", "withdrawn"]


class Cited(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: int = Field(description="1-based page number from the '===== PAGE n =====' marker")
    quote: str = Field(description="verbatim excerpt (<=300 chars) from that page that supports the value")


class TextFact(Cited):
    value: str


class DateFact(Cited):
    value: date = Field(description="ISO date")


class Product(Cited):
    name: str = Field(description="product/goods as named in the document")
    is_standards: list[str] = Field(default_factory=list, description="IS numbers printed for this product, e.g. 'IS 15885 (Part 2/Sec 13): 2010'")


class HsCode(Cited):
    code: str = Field(description="HS/ITC-HS code exactly as printed; ONLY if printed in the document")


class Extraction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_qco: bool | None = Field(description="true if the document is a Quality Control Order or an amendment/rescission/extension of one")
    is_qco_quote: Cited | None = None
    order_title: TextFact | None = Field(default=None, description="title of the Order as printed, e.g. '... (Quality Control) Order, 2025'")
    ministry: TextFact | None = Field(default=None, description="issuing ministry/department; 'quote' must contain its name")
    change_type: ChangeType | None = None
    change_type_quote: Cited | None = None
    notification_date: DateFact | None = None
    effective_date: DateFact | None = Field(default=None, description="date the Order comes into force; null if not stated")
    compliance_deadline: DateFact | None = Field(default=None, description="date by which products must comply (incl. extended/relaxed deadlines)")
    products: list[Product] = Field(default_factory=list)
    hs_codes: list[HsCode] = Field(default_factory=list, description="EMPTY unless an HS/ITC code is printed in the text")
    notes: str | None = Field(default=None, description="uncertainty or things a reviewer should check")
