"""The seven Gemma agents.

Each module exposes plain async functions rather than an agent class. Services
call them directly, which keeps the call graph readable and makes each agent
testable without constructing a runtime.

Shared machinery lives in runtime.py: schema-constrained calls with one repair
attempt, and the rule that every user-facing string is produced in English and
Bangla together.
"""

from app.agents import bicharok, dalil, khoji, lekhok, porter, prohori, shonchari

__all__ = ["bicharok", "dalil", "khoji", "lekhok", "porter", "prohori", "shonchari"]
