"""Saving the provider in Settings must reach research too (conn.llm), metered by the shared limiter."""

from __future__ import annotations

import secretary.controller.llm_settings as ls_module
from secretary.controller import Controller
from secretary.llm.metered import MeteredClient


class _Conn:
    pass


def test_rebuild_llm_updates_the_research_llm(monkeypatch):
    client, limiter = object(), object()
    monkeypatch.setattr(ls_module, "build_llm", lambda cfg, key: (client, limiter))
    monkeypatch.setattr(ls_module, "get_active_llm_key", lambda: "k" * 30)
    conn = _Conn()
    conn.llm = None  # as left by a start-up with no usable model
    controller = Controller(conn)
    controller.rebuild_llm()
    assert controller.llm is client and controller.limiter is limiter
    assert isinstance(conn.llm, MeteredClient)
    assert conn.llm._client is client and conn.llm._limiter is limiter


def test_rebuild_llm_without_a_model_clears_the_research_llm(monkeypatch):
    monkeypatch.setattr(ls_module, "build_llm", lambda cfg, key: (None, None))
    monkeypatch.setattr(ls_module, "get_active_llm_key", lambda: None)
    conn = _Conn()
    conn.llm = object()
    Controller(conn).rebuild_llm()
    assert conn.llm is None
