"""Ride lifecycle as an explicit state machine.

Main path: REQUESTED, SEARCHING, MATCHED, DRIVER_EN_ROUTE, DRIVER_ARRIVED,
IN_TRIP, COMPLETED. NO_DRIVER ends a ride that found no driver.

EventBridge does not guarantee ordering, so a transition may skip forward
along the main path (for example MATCHED arriving before SEARCHING). Moving
backwards or leaving a terminal state is rejected.
"""
from shared import events

REQUESTED = "REQUESTED"
SEARCHING = "SEARCHING"
MATCHED = "MATCHED"
DRIVER_EN_ROUTE = "DRIVER_EN_ROUTE"
DRIVER_ARRIVED = "DRIVER_ARRIVED"
IN_TRIP = "IN_TRIP"
COMPLETED = "COMPLETED"
NO_DRIVER = "NO_DRIVER"

MAIN_PATH = (REQUESTED, SEARCHING, MATCHED, DRIVER_EN_ROUTE, DRIVER_ARRIVED, IN_TRIP, COMPLETED)
TERMINAL = (COMPLETED, NO_DRIVER)

STATE_FOR_EVENT = {
    events.RIDE_REQUESTED: REQUESTED,
    events.RIDE_SEARCHING: SEARCHING,
    events.RIDE_MATCHED: MATCHED,
    events.RIDE_NO_DRIVER: NO_DRIVER,
    events.DRIVER_EN_ROUTE: DRIVER_EN_ROUTE,
    events.DRIVER_ARRIVED: DRIVER_ARRIVED,
    events.TRIP_STARTED: IN_TRIP,
    events.TRIP_COMPLETED: COMPLETED,
}


class InvalidTransition(Exception):
    pass


def allowed_previous(target):
    """States from which `target` may be entered."""
    if target == REQUESTED:
        return ()
    if target == NO_DRIVER:
        return (REQUESTED, SEARCHING)
    return MAIN_PATH[:MAIN_PATH.index(target)]


def check(current, target):
    if current not in allowed_previous(target):
        raise InvalidTransition(f"{current} to {target}")
