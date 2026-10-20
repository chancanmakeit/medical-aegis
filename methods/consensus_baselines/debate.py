"""PLACEHOLDER — to be replaced by the port of ConSensus baselines/debate."""
from methods.mas_base import MAS


class SensingDebate_Main(MAS):
    def __init__(self, general_config, method_config_name="config_sensing"):
        super().__init__(general_config, method_config_name=method_config_name)
        raise NotImplementedError("consensus_debate not ported yet")
