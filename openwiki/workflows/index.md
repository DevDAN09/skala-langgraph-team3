# Files

- [End-to-End Evaluation Workflow](end-to-end-evaluation.md) - End-to-end runtime path for evaluating KIVI and CXL-PNM, from INITIAL_INPUT_STATE through parallel paper and market research, stakeholder chaining, evidence audit and bounded retries, dual TRL synthesis, Jinja2 report generation, Markdown persistence, and optional PDF export with graceful fallbacks.
- [Evidence Audit, Fast-Fail, and Targeted Retry](evidence-audit-and-retry.md) - The evidence-audit node validates claims with four deterministic fast-fail rules and an optional structured R5 factuality judge. It resolves each issue to an owning research agent, limits retries per agent, and sends unresolved terminal gaps to synthesis.
