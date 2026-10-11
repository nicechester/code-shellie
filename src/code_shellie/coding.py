"""Rules the agent follows whenever it writes or changes code."""

CODING_GUIDANCE = (
    "When you write or change code, give each module one responsibility: if a file starts doing a second job, "
    "put that job in its own module instead of adding to the file. "
    "Add or update tests for every behavior you change, in the test file for that module, and create that file "
    "if it does not exist yet. "
    "Run the test suite before you report the change as done, and say what you ran and what it showed."
)
