"""Mammotion Lawn Mower."""

from __future__ import annotations

import asyncio
from copy import copy
from datetime import time
from typing import Any, cast

import voluptuous as vol
from homeassistant.components.lawn_mower import DOMAIN as LAWN_MOWER_DOMAIN
from homeassistant.components.lawn_mower import (
    LawnMowerActivity,
    LawnMowerEntity,
    LawnMowerEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import service
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from pymammotion.data.model.report_info import DeviceData, ReportData
from pymammotion.utility.constant.device_constant import WorkMode
from pymammotion.utility.device_type import DeviceType

from . import MammotionConfigEntry
from .const import COMMAND_EXCEPTIONS, DOMAIN, LOGGER
from .coordinator import MammotionReportUpdateCoordinator
from .entity import MammotionBaseEntity

SERVICE_START_MOWING = "start_mow"
SERVICE_CANCEL_JOB = "cancel_job"
SERVICE_START_STOP_BLADES = "start_stop_blades"
SERVICE_SET_NON_WORK_HOURS = "set_non_work_hours"
SERVICE_RESET_BLADE_TIME = "reset_blade_time"
SERVICE_SET_BLADE_WARNING_TIME = "set_blade_warning_time"

START_MOW_SCHEMA = {
    vol.Optional("modify", default=False): cv.boolean,
    vol.Optional("plan_only", default=False): cv.boolean,
    vol.Optional("is_mow", default=True): cv.boolean,
    vol.Optional("is_dump", default=True): cv.boolean,
    vol.Optional("is_edge", default=False): cv.boolean,
    vol.Optional("collect_grass_frequency", default=10): vol.All(
        vol.Coerce(int), vol.Range(min=5, max=100)
    ),
    vol.Optional("border_mode", default=1): vol.All(vol.Coerce(int), vol.In([0, 1])),
    vol.Optional("job_version", default=0): vol.Coerce(int),
    vol.Optional("job_id", default=0): vol.Coerce(int),
    vol.Optional("speed", default=0.3): vol.All(
        vol.Coerce(float), vol.Range(min=0.2, max=1.2)
    ),
    vol.Optional("ultra_wave", default=2): vol.All(
        vol.Coerce(int), vol.In([0, 1, 2, 10, 11])
    ),
    vol.Optional("channel_mode", default=0): vol.All(
        vol.Coerce(int), vol.In([0, 1, 2, 3])
    ),
    vol.Optional("channel_width", default=25): vol.All(
        vol.Coerce(int), vol.Range(min=5, max=35)
    ),
    vol.Optional("rain_tactics", default=1): vol.All(vol.Coerce(int), vol.In([0, 1])),
    vol.Optional("blade_height", default=25): vol.All(
        vol.Coerce(int), vol.Range(min=15, max=100)
    ),
    vol.Optional("toward", default=0): vol.All(
        vol.Coerce(int), vol.Range(min=-180, max=180)
    ),
    vol.Optional("toward_included_angle", default=0): vol.All(
        vol.Coerce(int), vol.Range(min=-180, max=180)
    ),
    vol.Optional("toward_mode", default=0): vol.All(vol.Coerce(int), vol.In([0, 1, 2])),
    vol.Optional("mowing_laps", default=1): vol.All(
        vol.Coerce(int), vol.In([0, 1, 2, 3, 4])
    ),
    vol.Optional("obstacle_laps", default=1): vol.All(
        vol.Coerce(int), vol.In([0, 1, 2, 3, 4])
    ),
    vol.Optional("start_progress", default=0): vol.All(
        vol.Coerce(int), vol.Range(min=0, max=100)
    ),
    vol.Optional("areas", default=[]): vol.All(cv.ensure_list, [cv.entity_id]),
}

START_STOP_BLADES_SCHEMA = {
    vol.Required("start_stop", default=True): cv.boolean,
    vol.Optional("blade_height", default=30): vol.All(
        vol.Coerce(int), vol.Range(min=15, max=100)
    ),
}

SET_NON_WORK_HOURS_SCHEMA = {
    vol.Required("start_time"): cv.time,
    vol.Required("end_time"): cv.time,
}

SET_BLADE_WARNING_TIME_SCHEMA = {
    vol.Required("hours"): vol.All(vol.Coerce(int), vol.Range(min=1, max=9999)),
}


def get_entity_attribute(
    hass: HomeAssistant, entity_id: str, attribute_name: str
) -> str | None:
    """Return a named attribute from a HA entity state, or None if unavailable."""
    # Get the state object of the entity
    entity = hass.states.get(entity_id)

    # Check if the entity exists and has attributes
    if entity and attribute_name in entity.attributes:
        # Return the specific attribute
        return cast(str | None, entity.attributes.get(attribute_name))
    # Return None if the entity or attribute does not exist
    return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MammotionConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Mammotion Lawn Mower config entry."""
    mammotion_devices = entry.runtime_data.mowers

    entities = [
        MammotionLawnMowerEntity(mower.reporting_coordinator)
        for mower in mammotion_devices
    ]

    async_add_entities(entities)

    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_START_MOWING,
        entity_domain=LAWN_MOWER_DOMAIN,
        schema=START_MOW_SCHEMA,
        func="async_start_mowing",
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_CANCEL_JOB,
        entity_domain=LAWN_MOWER_DOMAIN,
        schema=None,
        func="async_cancel",
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_START_STOP_BLADES,
        entity_domain=LAWN_MOWER_DOMAIN,
        schema=START_STOP_BLADES_SCHEMA,
        func="async_start_stop_blades",
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_SET_NON_WORK_HOURS,
        entity_domain=LAWN_MOWER_DOMAIN,
        schema=SET_NON_WORK_HOURS_SCHEMA,
        func="async_set_non_work_hours",
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_RESET_BLADE_TIME,
        entity_domain=LAWN_MOWER_DOMAIN,
        schema=None,
        func="async_reset_blade_time",
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        SERVICE_SET_BLADE_WARNING_TIME,
        entity_domain=LAWN_MOWER_DOMAIN,
        schema=SET_BLADE_WARNING_TIME_SCHEMA,
        func="async_set_blade_warning_time",
    )


class MammotionLawnMowerEntity(MammotionBaseEntity, LawnMowerEntity):  # type: ignore[misc]
    """Representation of a Mammotion Lawn Mower."""

    _attr_supported_features = (
        LawnMowerEntityFeature.DOCK
        | LawnMowerEntityFeature.PAUSE
        | LawnMowerEntityFeature.START_MOWING
    )

    def __init__(self, coordinator: MammotionReportUpdateCoordinator) -> None:
        """Initialize the Lawn Mower."""
        super().__init__(coordinator, "mower")
        self._attr_name = None  # main feature of device

    @property
    def rpt_dev_status(self) -> DeviceData:
        """Return the device status."""
        return self.coordinator.data.report_data.dev

    @property
    def report_data(self) -> ReportData:
        """Return the report data."""
        return self.coordinator.data.report_data

    @property
    def activity(self) -> LawnMowerActivity | None:
        """Return the state of the mower."""

        charge_state = self.rpt_dev_status.charge_state
        mode = self.rpt_dev_status.sys_status
        if mode is None:
            return None

        LOGGER.debug("activity mode %s", mode)
        if mode == WorkMode.MODE_PAUSE or (
            mode == WorkMode.MODE_READY and charge_state == 0
        ):
            return LawnMowerActivity.PAUSED
        if mode == WorkMode.MODE_WORKING:
            return LawnMowerActivity.MOWING
        if mode == WorkMode.MODE_RETURNING:
            return LawnMowerActivity.RETURNING
        if mode == WorkMode.MODE_LOCK:
            return LawnMowerActivity.ERROR
        if mode == WorkMode.MODE_READY and charge_state != 0:
            return LawnMowerActivity.DOCKED
        return None

    async def async_start_mowing(self, **kwargs: Any) -> None:
        """Start mowing."""
        trans_key = "pause_failed"

        await self.coordinator.async_ensure_fresh_state()

        if kwargs:
            entity_ids = kwargs.pop("areas", [])
            attributes = [
                # TODO this should not need to be cast.
                int(entity_hash)
                for entity_id in entity_ids
                if (entity_hash := get_entity_attribute(self.hass, entity_id, "hash"))
                is not None
            ]
            modify_plan = kwargs.pop("modify", False)
            plan_only = kwargs.pop("plan_only", False)

            # Merge onto coordinator's restored settings so UI-configured values
            # (speed, blade_height, etc.) are preserved when not explicitly provided.
            operational_settings = copy(self.coordinator.operation_settings)
            operational_settings.areas = list(dict.fromkeys(attributes))
            for key, value in kwargs.items():
                setattr(operational_settings, key, value)
            if DeviceType.is_yuka(self.coordinator.device_name):
                operational_settings.blade_height = -10
            LOGGER.debug(kwargs)
            LOGGER.debug(operational_settings)
        else:
            operational_settings = self.coordinator.operation_settings
            modify_plan = False
            plan_only = False

        # If no areas are selected (either the user did not pass any, or the
        # zone switches were reset by a restart — OperationSettings is in-memory
        # only), fall back to the zones the mower itself remembers from its
        # last mow.  This mirrors the phone app's behaviour: pressing Start
        # without picking zones uses the last-known set.
        if not operational_settings.areas:
            device_work = getattr(self.coordinator.data, "work", None)
            if device_work is not None and device_work.zone_hashs:
                fallback_zones = list(dict.fromkeys(device_work.zone_hashs))
                LOGGER.info(
                    "[start_mowing] no areas selected — falling back to mower's "
                    "last-used zones: %s",
                    fallback_zones,
                )
                operational_settings.areas = fallback_zones
            else:
                LOGGER.warning(
                    "[start_mowing] no areas selected AND mower has no stored "
                    "zones — the mow will likely start and immediately return "
                    "to dock (nothing to mow). Toggle on the zone switches "
                    "in HA, or start once from the phone app to populate "
                    "the mower's stored zones."
                )

        # check if job in progress
        #
        mode = self.rpt_dev_status.sys_status
        breakpoint_info = self.report_data.work.bp_info
        charge_state = self.rpt_dev_status.charge_state

        # === Command tracing: capture mower state at command entry =============
        LOGGER.info(
            "[start_mowing] entry — device=%s mode=%s charge_state=%s "
            "breakpoint_info=%s modify_plan=%s plan_only=%s areas=%s",
            self.coordinator.device_name,
            mode,
            charge_state,
            breakpoint_info,
            modify_plan,
            plan_only,
            getattr(operational_settings, "areas", None),
        )
        # =======================================================================

        # === Diagnostic: dump the mower's stored plans + work object ===========
        # This tells us how the mower expects to be started. If there are named
        # plans, we should start via start_task(plan_id) instead of building an
        # ad-hoc route.
        try:
            data = self.coordinator.data
            plans = getattr(getattr(data, "map", None), "plan", {}) or {}
            LOGGER.info(
                "[start_mowing] DIAG — mower has %d stored plan(s)", len(plans)
            )
            for pid, plan in plans.items():
                LOGGER.info(
                    "[start_mowing] DIAG plan id=%s task_name=%r job_name=%r "
                    "zone_hashs=%s area=%s knife_height=%s edge_mode=%s speed=%s",
                    pid,
                    getattr(plan, "task_name", None),
                    getattr(plan, "job_name", None),
                    getattr(plan, "zone_hashs", None),
                    getattr(plan, "area", None),
                    getattr(plan, "knife_height", None),
                    getattr(plan, "edge_mode", None),
                    getattr(plan, "speed", None),
                )
            work = getattr(data, "work", None)
            if work is not None:
                LOGGER.info(
                    "[start_mowing] DIAG work — zone_hashs=%s job_id=%s job_ver=%s "
                    "job_mode=%s bp_info=%s path_hash=%s ub_path_hash=%s",
                    getattr(work, "zone_hashs", None),
                    getattr(work, "job_id", None),
                    getattr(work, "job_ver", None),
                    getattr(work, "job_mode", None),
                    getattr(work, "bp_info", None),
                    getattr(work, "path_hash", None),
                    getattr(work, "ub_path_hash", None),
                )
            areas_map = getattr(getattr(data, "map", None), "area", {}) or {}
            LOGGER.info(
                "[start_mowing] DIAG — mower map has %d area(s): keys=%s",
                len(areas_map),
                list(areas_map.keys()),
            )
        except Exception as diag_exc:  # noqa: BLE001
            LOGGER.warning("[start_mowing] DIAG dump failed: %s", diag_exc)
        # =======================================================================



        if mode in (
            WorkMode.MODE_PAUSE,
            WorkMode.MODE_READY,
            WorkMode.MODE_RETURNING,
            WorkMode.MODE_WORKING,
            WorkMode.MODE_INITIALIZATION,
        ):
            try:
                if modify_plan:
                    LOGGER.info("[start_mowing] branch=modify_plan")
                    await self.coordinator.async_modify_plan_route(operational_settings)
                    return

                if kwargs:
                    LOGGER.debug("[start_mowing] cancelling current job before start")
                    await self.async_cancel()

                if mode == WorkMode.MODE_RETURNING:
                    LOGGER.info(
                        "[start_mowing] branch=cancel_return_to_dock (mode was RETURNING)"
                    )
                    trans_key = "dock_cancel_failed"
                    await self.coordinator.async_send_and_wait(
                        "cancel_return_to_dock", "todev_taskctrl_ack"
                    )
                    await self.coordinator.async_request_report_snapshot()
                    mode = self.rpt_dev_status.sys_status
                    LOGGER.info(
                        "[start_mowing] mode after cancel_return_to_dock: %s", mode
                    )
                if mode == WorkMode.MODE_PAUSE:
                    trans_key = "resume_failed"
                    if breakpoint_info != 0:
                        LOGGER.info(
                            "[start_mowing] branch=resume_execute_task (PAUSE + breakpoint=%s)",
                            breakpoint_info,
                        )
                        await self.coordinator.async_send_command("resume_execute_task")
                        await self.coordinator.async_send_and_wait(
                            "query_generate_route_information", "bidire_reqconver_path"
                        )
                    else:
                        LOGGER.warning(
                            "[start_mowing] mode=PAUSE but breakpoint_info=0 — "
                            "no resume sent (this can swallow the start command)"
                        )
                if mode in (WorkMode.MODE_READY, WorkMode.MODE_INITIALIZATION):
                    trans_key = "start_failed"

                    # If the mower is sitting on the dock (charge_state != 0),
                    # the firmware silently rejects start_job.  The phone app
                    # sends leave_dock first and waits for the mower to physically
                    # disconnect before proceeding.  We mirror that here — the
                    # command ack alone is not enough; charge_state has to reach 0.
                    if charge_state != 0:
                        LOGGER.info(
                            "[start_mowing] mower is docked (charge_state=%s) — "
                            "sending leave_dock before start_job",
                            charge_state,
                        )
                        await self.coordinator.async_leave_dock()

                        # Poll charge_state up to 30 s waiting for the physical
                        # disconnect.  The report snapshot is asynchronous over
                        # MQTT, so we request one, sleep briefly, then re-read.
                        wait_deadline = 30
                        for attempt in range(wait_deadline):
                            await asyncio.sleep(1)
                            await self.coordinator.async_request_report_snapshot()
                            new_charge_state = self.rpt_dev_status.charge_state
                            new_mode = self.rpt_dev_status.sys_status
                            LOGGER.debug(
                                "[start_mowing] leave_dock poll #%d: mode=%s charge_state=%s",
                                attempt + 1,
                                new_mode,
                                new_charge_state,
                            )
                            if new_charge_state == 0:
                                LOGGER.info(
                                    "[start_mowing] mower left dock after %d s "
                                    "(mode=%s charge_state=%s)",
                                    attempt + 1,
                                    new_mode,
                                    new_charge_state,
                                )
                                mode = new_mode
                                charge_state = new_charge_state
                                break
                        else:
                            LOGGER.warning(
                                "[start_mowing] mower did not leave dock within %d s "
                                "(charge_state still %s) — continuing anyway, but "
                                "start_job may be rejected by firmware",
                                wait_deadline,
                                self.rpt_dev_status.charge_state,
                            )
                            mode = self.rpt_dev_status.sys_status
                            charge_state = self.rpt_dev_status.charge_state

                    # Root cause of the "starts then returns to dock after a few
                    # seconds" bug: async_plan_route only sent
                    # generate_route_information and then start_job — but it never
                    # fetched the actual cover-path frames the mower needs to
                    # follow. The mower ended up with a route *header* but no path
                    # *data*, so it started, had nothing to follow, and returned
                    # to the dock.
                    #
                    # The pymammotion library's own mow-start flow runs the full
                    # MowPathSaga (get_all_boundary_hash_list -> generate_route ->
                    # get_line_info_list -> collect cover_path_upload frames).
                    # async_plan_route_full runs that complete saga.

                    # Populate operation_settings from the mower's stored work
                    # data where it has real values (job_mode etc). areas is kept
                    # as the user's selection.
                    device_work = getattr(self.coordinator.data, "work", None)
                    if device_work is not None:
                        operational_settings.toward = device_work.toward
                        operational_settings.toward_mode = device_work.toward_mode
                        operational_settings.toward_included_angle = (
                            device_work.toward_included_angle
                        )
                        operational_settings.mowing_laps = device_work.edge_mode
                        operational_settings.job_mode = device_work.job_mode

                    if breakpoint_info != 0:
                        LOGGER.info(
                            "[start_mowing] branch=resume_existing_route "
                            "(breakpoint=%s) — querying stored route then starting",
                            breakpoint_info,
                        )
                        await self.coordinator.async_send_and_wait(
                            "query_generate_route_information", "bidire_reqconver_path"
                        )
                        if not plan_only:
                            await self.coordinator.async_send_command("start_job")
                            LOGGER.info("[start_mowing] start_job sent (resume)")
                        return

                    LOGGER.info(
                        "[start_mowing] branch=plan_route_full_then_start (mode=%s) — "
                        "speed=%s blade_height=%s mowing_laps=%s job_mode=%s "
                        "channel_mode=%s channel_width=%s areas=%s",
                        mode,
                        operational_settings.speed,
                        operational_settings.blade_height,
                        operational_settings.mowing_laps,
                        operational_settings.job_mode,
                        operational_settings.channel_mode,
                        operational_settings.channel_width,
                        operational_settings.areas,
                    )
                    LOGGER.info(
                        "[start_mowing] running full MowPathSaga "
                        "(plan + fetch cover path)..."
                    )
                    plan_ok = await self.coordinator.async_plan_route_full(
                        operational_settings
                    )
                    LOGGER.info(
                        "[start_mowing] async_plan_route_full returned %s", plan_ok
                    )
                    if plan_ok:
                        if not plan_only:
                            LOGGER.info(
                                "[start_mowing] sending start_job and waiting for "
                                "zone_start_precent_t ack..."
                            )
                            await self.coordinator.async_send_and_wait(
                                "start_job", "zone_start_precent_t"
                            )
                            LOGGER.info("[start_mowing] start_job ack received")
                    else:
                        LOGGER.warning(
                            "[start_mowing] async_plan_route_full returned False — "
                            "start_job NOT sent"
                        )

            except COMMAND_EXCEPTIONS as exc:
                LOGGER.error(
                    "[start_mowing] command failed (trans_key=%s): %s: %s",
                    trans_key,
                    type(exc).__name__,
                    exc,
                )
                raise HomeAssistantError(
                    translation_domain=DOMAIN, translation_key=trans_key
                ) from exc
            finally:
                await self.coordinator.async_request_report_snapshot()
        else:
            LOGGER.warning(
                "[start_mowing] no-op — mower mode %s is not in the actionable set "
                "(PAUSE, READY, RETURNING, WORKING, INITIALIZATION). "
                "Command will be silently ignored.",
                mode,
            )

    async def async_dock(self) -> None:
        """Start docking."""
        trans_key = "dock_failed"

        await self.coordinator.async_start_report_stream()
        charge_state = self.rpt_dev_status.charge_state
        mode = self.rpt_dev_status.sys_status

        LOGGER.info(
            "[dock] entry — device=%s mode=%s charge_state=%s",
            self.coordinator.device_name,
            mode,
            charge_state,
        )

        if mode is None:
            LOGGER.warning("[dock] aborted — mower mode is None (device not ready)")
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="device_not_ready"
            )

        # Already docked/charging — nothing to do.
        if charge_state != 0:
            LOGGER.info(
                "[dock] no-op — charge_state=%s (mower already docked/charging)",
                charge_state,
            )
            return

        # Already on its way to the dock — no-op (do NOT cancel the return!
        # The upstream code sent cancel_return_to_dock here, which is the
        # opposite of what a "return to dock" action should do).
        if mode == WorkMode.MODE_RETURNING:
            LOGGER.info("[dock] no-op — mower already returning to dock")
            return

        if mode not in (
            WorkMode.MODE_WORKING,
            WorkMode.MODE_PAUSE,
            WorkMode.MODE_READY,
        ):
            LOGGER.warning(
                "[dock] no-op — mode %s is not in (WORKING, PAUSE, READY). "
                "Command ignored.",
                mode,
            )
            return

        # For WORKING / PAUSE / READY: send return_to_dock and let the firmware
        # handle the state transition.  The upstream code used to send
        # pause_execute_task first when WORKING, which put the mower into PAUSE
        # state before the dock command arrived; the firmware then rejected the
        # dock command, so the mower would pause but never return.
        try:
            LOGGER.info("[dock] branch=return_to_dock (mode=%s)", mode)
            await self.coordinator.async_send_command("return_to_dock")
        except COMMAND_EXCEPTIONS as exc:
            LOGGER.error(
                "[dock] command failed: %s: %s",
                type(exc).__name__,
                exc,
            )
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key=trans_key
            ) from exc
        finally:
            await self.coordinator.async_request_report_snapshot()

    async def async_pause(self) -> None:
        """Pause mower."""
        trans_key = "pause_failed"

        await self.coordinator.async_ensure_fresh_state()
        mode = self.rpt_dev_status.sys_status

        LOGGER.info(
            "[pause] entry — device=%s mode=%s",
            self.coordinator.device_name,
            mode,
        )

        if mode is None:
            LOGGER.warning("[pause] aborted — mower mode is None (device not ready)")
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="device_not_ready"
            )

        if mode in (
            WorkMode.MODE_WORKING,
            WorkMode.MODE_RETURNING,
        ):
            try:
                if mode == WorkMode.MODE_WORKING:
                    LOGGER.info("[pause] branch=pause_execute_task (mode=WORKING)")
                    trans_key = "pause_failed"
                    await self.coordinator.async_send_command("pause_execute_task")
                if mode == WorkMode.MODE_RETURNING:
                    LOGGER.info("[pause] branch=cancel_return_to_dock (mode=RETURNING)")
                    trans_key = "dock_cancel_failed"
                    await self.coordinator.async_send_command("cancel_return_to_dock")
            except COMMAND_EXCEPTIONS as exc:
                LOGGER.error(
                    "[pause] command failed (trans_key=%s): %s: %s",
                    trans_key,
                    type(exc).__name__,
                    exc,
                )
                raise HomeAssistantError(
                    translation_domain=DOMAIN, translation_key=trans_key
                ) from exc
            finally:
                await self.coordinator.async_request_report_snapshot()
        else:
            LOGGER.warning(
                "[pause] no-op — mode %s is not in (WORKING, RETURNING). Command ignored.",
                mode,
            )

    async def async_cancel(self) -> None:
        """Cancel Job."""
        trans_key = "pause_failed"

        await self.coordinator.async_ensure_fresh_state()
        mode = self.rpt_dev_status.sys_status
        if mode is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="device_not_ready"
            )

        if mode in (
            WorkMode.MODE_PAUSE,
            WorkMode.MODE_WORKING,
            WorkMode.MODE_RETURNING,
        ):
            try:
                if mode != WorkMode.MODE_PAUSE:
                    if mode == WorkMode.MODE_WORKING:
                        trans_key = "pause_failed"
                        await self.coordinator.async_send_command("pause_execute_task")
                    if mode == WorkMode.MODE_RETURNING:
                        trans_key = "dock_failed"
                        await self.coordinator.async_send_command(
                            "cancel_return_to_dock"
                        )
                    await self.coordinator.async_request_report_snapshot()
                    mode = self.rpt_dev_status.sys_status

                if mode == WorkMode.MODE_PAUSE:
                    trans_key = "pause_failed"
                    await self.coordinator.async_send_command("cancel_job")

            except COMMAND_EXCEPTIONS as exc:
                raise HomeAssistantError(
                    translation_domain=DOMAIN, translation_key=trans_key
                ) from exc
            finally:
                await self.coordinator.async_request_report_snapshot()

    async def async_start_stop_blades(self, **kwargs: Any) -> None:
        """Start/Stop Blades."""
        await self.coordinator.async_start_stop_blades(**kwargs)

    async def async_set_non_work_hours(self, **kwargs: Any) -> None:
        """Set Non Work Hours."""
        start_time: time = kwargs["start_time"]
        end_time: time = kwargs["end_time"]

        await self.coordinator.async_set_non_work_hours(
            start_time=start_time.strftime("%H:%M"), end_time=end_time.strftime("%H:%M")
        )

    async def async_reset_blade_time(self) -> None:
        """Reset blade used time to zero."""
        if DeviceType.is_luba1(self.coordinator.device_name):
            return
        await self.coordinator.async_reset_blade_time()

    async def async_set_blade_warning_time(self, hours: int) -> None:
        """Set blade replacement warning threshold in hours."""
        if DeviceType.is_luba1(self.coordinator.device_name):
            return
        await self.coordinator.async_set_blade_warning_time(hours=hours)

    async def async_added_to_hass(self) -> None:
        """Register callbacks and verify device linkage after HA setup."""
        await super().async_added_to_hass()

        # Ensure the entity is actually linked to a device
        if not self.coordinator.device_name:
            return

        device_registry = dr.async_get(self.hass)

        device = device_registry.async_get_device(
            identifiers={(DOMAIN, self.coordinator.device_name)}
        )

        if device:
            for conn_type, value in device.connections:
                if conn_type == dr.CONNECTION_NETWORK_MAC:
                    self.coordinator.data.mower_state.wifi_mac = value
                elif conn_type == dr.CONNECTION_BLUETOOTH:
                    self.coordinator.data.mower_state.ble_mac = value
