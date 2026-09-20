"""Auth helper routes: GET /api/me and the rotating sign-in design (GET /api/signin-variant)."""
from __future__ import annotations

import logging
import os
import random

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from .auth import authenticate
from .config import get_settings
from .db import get_db
from .models import SigninVariantLog

log = logging.getLogger("verbatim.auth")
router = APIRouter(prefix="/api")

VARIANTS = ("a", "b", "c", "d")


def variant_weights() -> list[float]:
    """SIGNIN_VARIANT_WEIGHTS="a=1,b=2,c=1,d=1" (missing letters count 0). Bad input means equal weights."""
    raw = os.environ.get("SIGNIN_VARIANT_WEIGHTS")
    if raw is None:
        raw = get_settings().signin_variant_weights
    equal = [1.0] * len(VARIANTS)
    if not raw or not raw.strip():
        return equal
    found: dict[str, float] = {}
    try:
        for part in raw.split(","):
            key, _, val = part.partition("=")
            key = key.strip().lower()
            if key not in VARIANTS or key in found:
                return equal
            w = float(val)
            if not (0 <= w <= 1000):  # also false for NaN
                return equal
            found[key] = w
    except ValueError:
        return equal
    weights = [found.get(v, 0.0) for v in VARIANTS]
    return weights if sum(weights) > 0 else equal


def pick_variant() -> str:
    return random.choices(VARIANTS, weights=variant_weights(), k=1)[0]


@router.get("/me")
def me(request: Request, response: Response, db: Session = Depends(get_db)):
    user, claims = authenticate(request, db)
    response.headers["Cache-Control"] = "no-store"
    out: dict = {"id": user.id}
    email = claims.get("email")
    if isinstance(email, str) and email:
        out["email"] = email[:320]
    return out


@router.get("/signin-variant")
def signin_variant(response: Response, db: Session = Depends(get_db)):
    """Public. Picks a design at random and counts it. Stores the variant and a timestamp only."""
    variant = pick_variant()
    try:
        db.add(SigninVariantLog(variant=variant))  # no IP, no user agent, no cookie
        db.commit()
    except Exception:  # never block sign-in because the counter failed
        db.rollback()
        log.warning("could not log sign-in variant")
    response.headers["Cache-Control"] = "no-store"
    return {"variant": variant}
