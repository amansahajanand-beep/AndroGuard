"""Dynamic analysis: run the APK on an Android emulator and inspect it.

Distinct from ``app.modules.screenshots``, which extracts static image assets from
the APK archive. Nothing here requires Android Studio; the device is driven purely
through adb and the emulator CLI, both located via ADB_PATH / EMULATOR_PATH /
ANDROID_SDK_ROOT.

Phase 1: device lifecycle (boot, install, launch, stop).
Phase 2: UIAutomator dump + deterministic input actions (no LLM).
Phase 3: screenshot capture + visual / ad-placement state fingerprints.
Phase 4: deterministic exploration engine + navigation graph (no LLM / no S3).
Phase 5: advertisement placement discovery across multiple runs (deterministic).
"""

from app.modules.exploration.actions import (
    Action,
    ActionResult,
    BackAction,
    CoordinateTapAction,
    HomeAction,
    MenuAction,
    SwipeAction,
    TapAction,
    WaitAction,
)
from app.modules.exploration.action_planner import PlannedAction
from app.modules.exploration.adb import (
    AdbDevice,
    AndroidADB,
    CommandResult,
    adb_available,
    capability_report,
    find_adb,
)
from app.modules.exploration.apk_manager import APKManager
from app.modules.exploration.emulator import EmulatorManager, emulator_available, find_emulator
from app.modules.exploration.explorer import (
    ExplorationEngine,
    ExplorationLimits,
    ExplorationSession,
    run_exploration,
    session_to_exploration_result,
)
from app.modules.exploration.image_hasher import ImageHasher, ImageHashResult
from app.modules.exploration.launcher import AppLauncher, LaunchOutcome
from app.modules.exploration.navigation_graph import NavEdge, NavigationGraph
from app.modules.exploration.prior_knowledge import ExplorationPrior, prior_from_analysis
from app.modules.exploration.blueprint import (
    apply_blueprint_to_prior,
    build_coverage,
    mine_blueprint,
)
from app.modules.exploration.journey import (
    JourneyState,
    classify_screen,
    expand_section_goals,
    filter_candidates_for_step,
)
from app.modules.exploration.observation import Observation
from app.modules.exploration.observation_builder import build_observation
from app.modules.exploration.agent_state import (
    AgentGoal,
    AgentState,
    AgentStatus,
    FailedActionRecord,
    HistoryEntry,
    RecoveryRecord,
)
from app.modules.exploration.planner import ExplorationPlanner, PlanResult
from app.modules.exploration.executor import ActionExecutor, ExecutorResult, ALLOWED_ACTION_KINDS
from app.modules.exploration.verifier import ActionVerifier, VerifyOutcome, VerifyResult
from app.modules.exploration.supervisor import (
    ExplorationSupervisor,
    SupervisorContext,
    SupervisorDecision,
    SupervisorDecisionKind,
)
from app.modules.exploration.screenshot_manager import CapturedScreenshot, ScreenshotManager
from app.modules.exploration.screenshot_storage import (
    ScreenshotMetadata,
    ScreenshotStorage,
    exploration_state_key,
    hitl_screenshot_key,
    local_hitl_dir,
    local_screenshots_dir,
    publish_exploration_screenshots,
)
from app.modules.exploration.state_detector import (
    AdLayoutFingerprint,
    ScreenStateRecord,
    StateDecision,
    StateDetector,
    VisualFingerprint,
)
from app.modules.exploration.ad_discovery import (
    AdDiscoveryLimits,
    AdPlacementCatalog,
    AdPlacementDetector,
    AdPlacementFingerprint,
    AdPlacementRecord,
)
from app.modules.exploration.ad_goals import (
    AdGoalGenerator,
    AdPlacementDiscovery,
    GoalEvaluator,
    seed_ad_goals_from_intelligence,
)
from app.modules.exploration.ad_explorer import (
    AdAwareExplorationEngine,
    AdExplorationCampaign,
    campaign_to_exploration_result,
    run_ad_exploration,
)
from app.modules.exploration.target import (
    LaunchTarget,
    launcher_activity,
    target_from_analysis,
    target_from_apk,
)
from app.modules.exploration.ui_controller import UIController, UiDump
from app.modules.exploration.ui_dump import filter_elements, parse_bounds, parse_ui_hierarchy
from app.modules.exploration.ui_element import UIElement

__all__ = [
    "ALLOWED_ACTION_KINDS",
    "APKManager",
    "Action",
    "ActionExecutor",
    "ActionResult",
    "ActionVerifier",
    "AdAwareExplorationEngine",
    "AdDiscoveryLimits",
    "AdExplorationCampaign",
    "AdLayoutFingerprint",
    "AdPlacementCatalog",
    "AdPlacementDetector",
    "AdPlacementDiscovery",
    "AdPlacementFingerprint",
    "AdPlacementRecord",
    "AdGoalGenerator",
    "GoalEvaluator",
    "AdbDevice",
    "AgentGoal",
    "AgentState",
    "AgentStatus",
    "AndroidADB",
    "AppLauncher",
    "BackAction",
    "CapturedScreenshot",
    "CommandResult",
    "CoordinateTapAction",
    "EmulatorManager",
    "ExecutorResult",
    "ExplorationEngine",
    "ExplorationLimits",
    "ExplorationPlanner",
    "ExplorationPrior",
    "ExplorationSession",
    "ExplorationSupervisor",
    "FailedActionRecord",
    "HistoryEntry",
    "HomeAction",
    "ImageHashResult",
    "ImageHasher",
    "JourneyState",
    "LaunchOutcome",
    "LaunchTarget",
    "MenuAction",
    "NavEdge",
    "NavigationGraph",
    "Observation",
    "PlanResult",
    "PlannedAction",
    "RecoveryRecord",
    "ScreenStateRecord",
    "ScreenshotManager",
    "ScreenshotMetadata",
    "ScreenshotStorage",
    "StateDecision",
    "StateDetector",
    "SupervisorContext",
    "SupervisorDecision",
    "SupervisorDecisionKind",
    "SwipeAction",
    "TapAction",
    "UIController",
    "UIElement",
    "UiDump",
    "VerifyOutcome",
    "VerifyResult",
    "VisualFingerprint",
    "WaitAction",
    "adb_available",
    "apply_blueprint_to_prior",
    "build_coverage",
    "build_observation",
    "capability_report",
    "campaign_to_exploration_result",
    "classify_screen",
    "emulator_available",
    "expand_section_goals",
    "exploration_state_key",
    "filter_candidates_for_step",
    "filter_elements",
    "find_adb",
    "find_emulator",
    "hitl_screenshot_key",
    "launcher_activity",
    "local_hitl_dir",
    "local_screenshots_dir",
    "mine_blueprint",
    "parse_bounds",
    "parse_ui_hierarchy",
    "prior_from_analysis",
    "publish_exploration_screenshots",
    "run_ad_exploration",
    "run_exploration",
    "session_to_exploration_result",
    "target_from_analysis",
    "target_from_apk",
]
