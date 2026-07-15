"""
Looping synthetic TEST FLIGHT for local UI / stage / frame testing.

Cycle: T-10m (Go) → T-0 (liftoff / live) → T+10m → reset to T-10m.
Never sent as phone notifications (is_test=True).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from . import config
from .cache import ensure_dirs
from .models import (
    Launch,
    MissionBrief,
    StreamLink,
    TimelineEvent,
    VehicleStats,
    PayloadStats,
)


def _load_net(now: datetime) -> datetime:
    ensure_dirs()
    path = config.TEST_FLIGHT_STATE
    pre = config.TEST_FLIGHT_PRE_SEC
    post = config.TEST_FLIGHT_POST_SEC
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            net = datetime.fromisoformat(data["net"])
            if net.tzinfo is None:
                net = net.replace(tzinfo=timezone.utc)
            # After T+post, roll forward
            if now > net + timedelta(seconds=post):
                net = now + timedelta(seconds=pre)
                path.write_text(
                    json.dumps({"net": net.isoformat()}, indent=2),
                    encoding="utf-8",
                )
            return net
        except (json.JSONDecodeError, KeyError, OSError, ValueError):
            pass
    net = now + timedelta(seconds=pre)
    path.write_text(json.dumps({"net": net.isoformat()}, indent=2), encoding="utf-8")
    return net


def make_test_launch(now: datetime | None = None) -> Launch:
    now = now or datetime.now(timezone.utc)
    net = _load_net(now)
    secs = (net - now).total_seconds()

    # Keep "live" for the whole loop so HOME frame-grab can be tested anytime
    if secs > 0:
        status, abbrev = "Go for Launch", "Go"
        webcast_live = True
        hold = ""
    elif secs > -config.TEST_FLIGHT_POST_SEC:
        status, abbrev = "In Flight", "In Flight"
        webcast_live = True
        hold = ""
    else:
        status, abbrev = "Go for Launch", "Go"
        webcast_live = True
        hold = ""

    countdown = [
        TimelineEvent(-600, "TEST Flight Director poll — GO for prop load", "countdown", "test"),
        TimelineEvent(-300, "Propellant load underway (simulated)", "countdown", "test"),
        TimelineEvent(-120, "Engine chill (simulated)", "countdown", "test"),
        TimelineEvent(-60, "Launch director verifies GO", "countdown", "test"),
        TimelineEvent(-10, "Startup sequence", "countdown", "test"),
        TimelineEvent(0, "Excitement guaranteed (test)", "countdown", "test"),
    ]
    flight = [
        TimelineEvent(0, "Liftoff", "flight", "test"),
        TimelineEvent(60, "Max Q (simulated)", "flight", "test"),
        TimelineEvent(150, "MECO / stage sep (simulated)", "flight", "test"),
        TimelineEvent(180, "Second engine start (simulated)", "flight", "test"),
        TimelineEvent(480, "SECO (simulated)", "flight", "test"),
        TimelineEvent(540, "Payload deploy demo (simulated)", "flight", "test"),
        TimelineEvent(600, "Test window complete — loop resets", "flight", "test"),
    ]

    brief = MissionBrief(
        provider="Spaceflight",
        mission_id="test-flight-loop",
        title="TEST Flight (local loop)",
        page_url="",
        countdown_title="Countdown (test)",
        flight_title="Flight Timeline (test)",
        disclaimer="Synthetic flight for UI testing — no phone alerts",
        paragraphs=[
            "This is a local TEST FLIGHT that loops every 20 minutes: "
            "T-10m → liftoff → T+10m → reset.",
            "Use it to exercise countdowns, stages, HOME layout, and live frame grabs. "
            "Phone notifications are disabled for this entry.",
        ],
        countdown_events=countdown,
        flight_events=flight,
        webcasts=[
            StreamLink(
                title="NASA Live (test stream source)",
                url=config.TEST_FLIGHT_STREAM,
                publisher="NASA",
                source="test",
                stream_type="Test Webcast",
                priority=1,
            )
        ],
    )

    return Launch(
        id=config.TEST_FLIGHT_ID,
        name="Test Vehicle | Test Flight Loop",
        status=status,
        status_abbrev=abbrev,
        status_description="Synthetic looping flight for Spaceflight UI tests.",
        net=net,
        window_start=net - timedelta(minutes=2),
        window_end=net + timedelta(minutes=8),
        net_precision="Second",
        probability=90,
        hold_reason=hold,
        webcast_live=webcast_live,
        provider="Spaceflight Test",
        provider_type="Test",
        provider_country="USA",
        pad="Test Pad 1",
        location="Local Simulation",
        vehicle=VehicleStats(
            name="Test Vehicle",
            full_name="Test Vehicle Block 1",
            family="Test",
            reusable=True,
            length_m=70.0,
            diameter_m=3.7,
            to_thrust_kn=7000.0,
            leo_capacity_kg=15000.0,
            description="Not a real rocket. Exists only inside this app.",
            total_launches=0,
            successful_launches=0,
        ),
        payload=PayloadStats(
            name="Test Flight Loop",
            type="Test",
            description="20-minute synthetic mission for feature testing.",
            orbit="Low Earth Orbit",
            orbit_abbrev="LEO",
            agencies=["Spaceflight"],
        ),
        streams=list(brief.webcasts),
        mission_brief=brief,
        timeline=countdown + flight,
        source="test",
        is_test=True,
    )


def inject_test_flight(launches: list[Launch]) -> list[Launch]:
    """Return a new list with the looping test flight first (always present)."""
    cleaned = [L for L in launches if L.id != config.TEST_FLIGHT_ID and not L.is_test]
    test = make_test_launch()
    return [test, *cleaned]
