"""Multi-agent baselines shipped with the ConSensus repo (baselines/{debate,mad,reconcile,cmd}),
re-implemented on the AEGIS MAS base class. Single-agent baselines (single_agent,
self_consistency, self_refine) are intentionally not ported: they are not multi-agent."""
from .debate import SensingDebate_Main
from .mad import SensingMAD_Main
from .reconcile import SensingReconcile_Main
from .cmd import SensingCMD_Main
