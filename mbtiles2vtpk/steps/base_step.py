"""
Abstract base class for all conversion steps.
"""

from abc import ABC, abstractmethod


class BaseStep(ABC):
    """Every conversion step must implement run()."""

    @abstractmethod
    def run(self) -> None:
        """Execute this conversion step."""
        raise NotImplementedError
