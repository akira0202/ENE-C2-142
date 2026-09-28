"""AgentCore Platform v1.0"""

# Export the manifest entry-point class so the dotted class in config/agent.yaml
# (src.graph.graph.MunicipalEnergyScenarioInputEvidenceExtractorGraph) resolves and
# `from src.graph import MunicipalEnergyScenarioInputEvidenceExtractorGraph` works too.
from src.graph.graph import MunicipalEnergyScenarioInputEvidenceExtractorGraph, build_agent

__all__ = ["MunicipalEnergyScenarioInputEvidenceExtractorGraph", "build_agent"]
