"""Sunucu giriş noktası. Çalıştırma: server klasöründe `uvicorn app.main:app --reload`"""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse


from .yapay_zeka import YapayZekaHatasi
from . import ayarlar, kapi
from .sema import HataCevabi, SoruCevabi, SoruIstegi


log = logging.getLogger("agentstack")

app = FastAPI(title="Agent Stack", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ayarlar.ARAYUZ_ADRESLERI,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


def hata(durum_kodu: int, kod: str, mesaj: str) -> JSONResponse:
    govde = HataCevabi(hata={"kod": kod, "mesaj": mesaj})
    return JSONResponse(status_code=durum_kodu, content=govde.model_dump())


@app.exception_handler(YapayZekaHatasi)
async def yapay_zeka_hatasi_yakala(_: Request, exc: YapayZekaHatasi):
    if exc.kod == "ZAMAN_ASIMI":
        return hata(504, "ZAMAN_ASIMI", exc.mesaj)
    return hata(502, "SAGLAYICI_HATASI", exc.mesaj)


@app.exception_handler(RequestValidationError)
async def gecersiz_istek(_: Request, __: RequestValidationError):
    return hata(422, "GECERSIZ_ISTEK", "İstek biçimi hatalı. Sohbet anlaşmasına bakın.")


@app.exception_handler(Exception)
async def beklenmeyen_hata(_: Request, exc: Exception):
    # İsteğin içeriğini loglamıyoruz: içinde şirket verisi olabilir.
    log.error("Beklenmeyen hata: %s", type(exc).__name__)
    return hata(500, "SUNUCU_HATASI", "Sunucuda beklenmeyen bir hata oluştu.")


@app.get("/saglik")
def saglik():
    return {"durum": "ayakta"}


@app.post(
    "/api/soru",
    response_model=SoruCevabi,
    responses={422: {"model": HataCevabi}, 500: {"model": HataCevabi}},
)
def soru_gonder(istek: SoruIstegi) -> SoruCevabi:
    return kapi.soru_isle(soru=istek.soru, kullanici=istek.kullanici)
