"""Plan gate written by the Lumen coding agent."""


def score(predicted_utility: float, risk: float, critic_weight: float = 0.65) -> float:
    if not 0 <= risk <= 1:
        raise ValueError("risk must be between 0 and 1")
    return predicted_utility * (1 - critic_weight * risk) - risk * 0.3


def allow(predicted_utility: float, risk: float, max_risk: float = 0.45) -> bool:
    if risk > max_risk:
        return False
    return score(predicted_utility, risk) >= 0.35
