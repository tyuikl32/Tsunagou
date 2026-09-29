"""Generated from protocol/schemas/queries/credential-delivery.schema.json; do not edit."""
# Source digest: sha256:d8f28cd42f456b068037a117808d602d5e945f5aa5a5424fe6c1aa16ee42a59b; generator: query-v1

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CredentialDeliveryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    receipt_id: str = Field(min_length=1)
    delivery_ref: str = Field(pattern='^delivery:[A-Za-z0-9_-]{24}$')
    delivery_status: Literal['pending', 'delivered', 'consumed', 'revoked', 'expired']
    created_at: str = Field(pattern='^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z$')
    expires_at: str = Field(pattern='^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z$')
    delivered_at: str | None = Field(pattern='^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z$')
    recovery_expires_at: str | None = Field(pattern='^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z$')
    consumed_at: str | None = Field(pattern='^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z$')
    revoked_at: str | None = Field(pattern='^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z$')
