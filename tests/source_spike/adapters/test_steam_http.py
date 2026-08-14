from __future__ import annotations

import json

from src.source_spike.adapters.steam_http import (
    HttpResponse, HttpSteamTransport, SteamTransportFailure, SteamTransportSuccess,
)


def wrapper(cursor="next"):
    return json.dumps({"success":1,"cursor":cursor,"reviews":[{"recommendationid":"1"}]}).encode()


def kwargs():
    return {"appid":730,"cursor":"*","num_per_page":20,"filter":"recent","language":"english",
        "review_type":"all","purchase_type":"all","filter_offtopic_activity":1,
        "request_timeout_seconds":10,"max_http_attempts":3,"max_total_elapsed_seconds":30,
        "max_retries":2,"base_backoff_seconds":2,"max_backoff_seconds":8,
        "min_request_interval_seconds":1}


def test_transport_builds_frozen_review_query_and_parses_page() -> None:
    seen=[]
    result=HttpSteamTransport(execute=lambda request,timeout:(seen.append(request.full_url) or HttpResponse(200,{},wrapper()))).fetch_reviews(**kwargs())
    assert isinstance(result, SteamTransportSuccess)
    assert "/appreviews/730?" in seen[0]
    assert "filter=recent" in seen[0] and "language=english" in seen[0]
    assert "review_type=all" in seen[0] and "purchase_type=all" in seen[0]
    assert result.page.cursor == "next"


def test_transport_enforces_global_minimum_interval() -> None:
    now=[0.0]; sleeps=[]
    def sleep(value): sleeps.append(value); now[0]+=value
    transport=HttpSteamTransport(execute=lambda request,timeout:HttpResponse(200,{},wrapper()),sleep=sleep,monotonic=lambda:now[0])
    assert isinstance(transport.fetch_reviews(**kwargs()), SteamTransportSuccess)
    assert isinstance(transport.fetch_reviews(**kwargs()), SteamTransportSuccess)
    assert sleeps == [1]


def test_transport_retries_429_and_records_rate_event() -> None:
    responses=[HttpResponse(429,{"Retry-After":"3"},b"{}"),HttpResponse(200,{},wrapper())]; sleeps=[]
    result=HttpSteamTransport(execute=lambda request,timeout:responses.pop(0),sleep=sleeps.append).fetch_reviews(**kwargs())
    assert isinstance(result, SteamTransportSuccess)
    assert result.http_attempt_count == 2 and result.retry_count == 1
    assert sleeps == [3]
    assert result.events[0]["category"] == "rate_limit"
    assert result.events[0]["rate_limit"]["retry_after_seconds"] == 3


def test_transport_rejects_malformed_and_nonretryable_response() -> None:
    malformed=HttpSteamTransport(execute=lambda request,timeout:HttpResponse(200,{},b'{"success":1}')).fetch_reviews(**kwargs())
    denied=HttpSteamTransport(execute=lambda request,timeout:HttpResponse(403,{},b"{}")).fetch_reviews(**kwargs())
    assert isinstance(malformed, SteamTransportFailure) and malformed.error_code == "malformed_wrapper"
    assert isinstance(denied, SteamTransportFailure) and denied.error_code == "http_403"
