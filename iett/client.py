"""Minimal client for İBB İETT SOAP web services."""

from __future__ import annotations

import json
import os
import re
import xml.etree.ElementTree as ET
from typing import Any

import requests
from dotenv import load_dotenv

from .store import IettStore, LINES_ALL_DATASET, STOPS_ALL_DATASET

SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
TEMPURI_NS = "http://tempuri.org/"

ENDPOINTS = {
    "master": "https://api.ibb.gov.tr/iett/UlasimAnaVeri/HatDurakGuzergah.asmx",
    "fleet": "https://api.ibb.gov.tr/iett/FiloDurum/SeferGerceklesme.asmx",
    "lines": "https://api.ibb.gov.tr/iett/ibb/ibb.asmx",
    "schedule": "https://api.ibb.gov.tr/iett/UlasimAnaVeri/PlanlananSeferSaati.asmx",
}


class IettApiError(RuntimeError):
    pass


class IettClient:
    """Call İETT open-data SOAP services (JSON helpers + XML line detail)."""

    def __init__(
        self,
        username: str | None = None,
        password: str | None = None,
        timeout: float = 30.0,
        session: requests.Session | None = None,
        *,
        use_cache: bool = True,
        store: IettStore | None = None,
    ) -> None:
        load_dotenv()
        self.username = username if username is not None else os.getenv("IETT_USERNAME") or None
        self.password = password if password is not None else os.getenv("IETT_PASSWORD") or None
        self.timeout = timeout
        self.session = session or requests.Session()
        self.use_cache = use_cache
        self.store = store or IettStore()

    def get_stop(self, stop_code: str, *, force_refresh: bool = False) -> list[dict[str, Any]]:
        """Stop metadata. Use stop_code='' to fetch all stops (slow, large)."""
        code = stop_code.strip()

        if self.use_cache and force_refresh and not code:
            self.store.invalidate_sync(STOPS_ALL_DATASET)

        if self.use_cache and not force_refresh:
            if not code:
                if self.store.stops_index_fresh():
                    return self.store.get_all_stops()
            else:
                row = self.store.get_stop_by_code(code)
                if row is not None:
                    return [row]

        data = self._call_json(
            ENDPOINTS["master"],
            "GetDurak_json",
            f"<tns:DurakKodu>{_xml_text(stop_code)}</tns:DurakKodu>",
        )
        if self.use_cache:
            self.store.upsert_stops(data)
            if not code:
                self.store.touch_sync(STOPS_ALL_DATASET)
        return data

    def search_stops(self, query: str, *, limit: int = 20, force_refresh: bool = False) -> list[dict[str, Any]]:
        """Match stop name, mahalle (ilçe), or semt (SYON); numeric query also matches stop code."""
        self.ensure_stops_index(force_refresh=force_refresh)
        return self.store.search_stops(query, limit=limit)

    def ensure_stops_index(self, *, force_refresh: bool = False) -> None:
        """Load all stops into SQLite when missing or TTL expired."""
        if not self.use_cache:
            return
        if force_refresh:
            self.store.invalidate_sync(STOPS_ALL_DATASET)
        if self.store.stops_index_fresh() and self.store.stops_count() > 0:
            return
        data = self._call_json(
            ENDPOINTS["master"],
            "GetDurak_json",
            "<tns:DurakKodu></tns:DurakKodu>",
        )
        self.store.upsert_stops(data)
        self.store.touch_sync(STOPS_ALL_DATASET)

    def search_lines(self, query: str, *, limit: int = 20, force_refresh: bool = False) -> list[dict[str, Any]]:
        """Match line code or name (Turkish-normalized)."""
        self.ensure_lines_index(force_refresh=force_refresh)
        return self.store.search_lines(query, limit=limit)

    def ensure_lines_index(self, *, force_refresh: bool = False) -> None:
        """Load all lines into SQLite when missing or TTL expired."""
        if not self.use_cache:
            return
        if force_refresh:
            self.store.invalidate_sync(LINES_ALL_DATASET)
            self.store.invalidate_kv("line", "")
        if (
            not force_refresh
            and self.store.lines_index_fresh()
            and self.store.lines_count() > 0
            and not self.store.lines_missing_names()
        ):
            return
        data = self.get_line("", force_refresh=force_refresh)
        self.store.upsert_lines(data)
        self.store.touch_sync(LINES_ALL_DATASET)

    def get_line(self, line_code: str, *, force_refresh: bool = False) -> list[dict[str, Any]]:
        """Line metadata. Use line_code='' for all lines."""
        code = line_code.strip()
        if self.use_cache and force_refresh:
            self.store.invalidate_kv("line", code)

        if self.use_cache and not force_refresh:
            cached = self.store.get_kv("line", code)
            if cached is not None:
                return cached

        data = self._call_json(
            ENDPOINTS["master"],
            "GetHat_json",
            f"<tns:HatKodu>{_xml_text(line_code)}</tns:HatKodu>",
        )
        if self.use_cache:
            self.store.set_kv("line", code, data)
            if not code:
                self.store.upsert_lines(data)
        return data

    def get_line_vehicles(self, line_code: str) -> list[dict[str, Any]]:
        """Live vehicle positions for one line (kapino, lat/lon, last update, …)."""
        return self._call_json(
            ENDPOINTS["fleet"],
            "GetHatOtoKonum_json",
            f"<tns:HatKodu>{_xml_text(line_code)}</tns:HatKodu>",
        )

    def get_fleet_positions(self) -> list[dict[str, Any]]:
        """Live positions for the whole fleet (~thousands of rows)."""
        return self._call_json(ENDPOINTS["fleet"], "GetFiloAracKonum_json", "")

    def get_line_schedule(self, line_code: str, *, force_refresh: bool = False) -> list[dict[str, Any]]:
        """Posted main-stop departure times for a line (PlanlananSeferSaati)."""
        if self.use_cache and force_refresh:
            self.store.invalidate_kv("schedule", line_code)

        if self.use_cache and not force_refresh:
            cached = self.store.get_kv("schedule", line_code)
            if cached is not None:
                return cached

        data = self._call_json(
            ENDPOINTS["schedule"],
            "GetPlanlananSeferSaati_json",
            f"<tns:HatKodu>{_xml_text(line_code)}</tns:HatKodu>",
        )
        if self.use_cache:
            self.store.set_kv("schedule", line_code, data)
        return data

    def get_line_stops(self, line_code: str, *, force_refresh: bool = False) -> list[dict[str, Any]]:
        """Ordered stops for a line (both directions), parsed from XML."""
        if self.use_cache and force_refresh:
            self.store.invalidate_kv("line_stops", line_code)

        if self.use_cache and not force_refresh:
            cached = self.store.get_kv("line_stops", line_code)
            if cached is not None:
                return cached

        root = self._call_xml(
            ENDPOINTS["lines"],
            "DurakDetay_GYY",
            f"<tns:hat_kodu>{_xml_text(line_code)}</tns:hat_kodu>",
        )
        rows: list[dict[str, Any]] = []
        for table in root.findall(".//{*}Table"):
            row = {child.tag.split("}", 1)[-1]: (child.text or "") for child in table}
            if row:
                rows.append(row)
        if self.use_cache:
            self.store.set_kv("line_stops", line_code, rows)
        return rows

    def _call_json(self, url: str, action: str, body_params: str) -> list[dict[str, Any]]:
        payload = self._extract_result_text(
            self._soap_post(url, action, body_params),
            f"{action}Result",
        )
        if not payload:
            return []
        data = json.loads(payload)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return [data]
        raise IettApiError(f"Unexpected JSON type from {action}: {type(data)}")

    def _call_xml(self, url: str, action: str, body_params: str) -> ET.Element:
        text = self._extract_result_text(self._soap_post(url, action, body_params), f"{action}Result")
        if not text:
            return ET.Element("empty")
        return ET.fromstring(text)

    def _soap_post(self, url: str, action: str, body_params: str) -> str:
        header = ""
        if self.username and self.password:
            header = f"""
  <soap:Header>
    <AuthHeader xmlns="{TEMPURI_NS}">
      <Username>{_xml_text(self.username)}</Username>
      <Password>{_xml_text(self.password)}</Password>
    </AuthHeader>
  </soap:Header>"""

        body = f"<tns:{action}>{body_params}</tns:{action}>" if body_params else f"<tns:{action}/>"
        envelope = f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="{SOAP_NS}" xmlns:tns="{TEMPURI_NS}">
{header}
  <soap:Body>
    {body}
  </soap:Body>
</soap:Envelope>"""

        response = self.session.post(
            url,
            data=envelope.encode("utf-8"),
            headers={
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": f"{TEMPURI_NS}{action}",
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.text

    @staticmethod
    def _extract_result_text(soap_xml: str, result_tag: str) -> str:
        match = re.search(
            rf"<(?:\w+:)?{re.escape(result_tag)}[^>]*>(?P<body>.*?)</(?:\w+:)?{re.escape(result_tag)}>",
            soap_xml,
            flags=re.DOTALL,
        )
        if not match:
            raise IettApiError(f"Missing {result_tag} in SOAP response")
        return match.group("body").strip()


def _xml_text(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
