# API usage investigation

## What the code does today

The agent sends one Gemini `generateContent` request for the prompt. When Gemini returns function calls, Code Shellie executes every call in that response, collects the results, and sends them together in the next `generateContent` request. A tool call is therefore not automatically one API request: the number of model requests depends on how many function-call rounds Gemini emits. Retries after rate limits and server errors make additional API requests. Web search uses a separate request and quota.

The local project index avoids some discovery calls. Its conventions and module summaries are cached by `HEAD`; the file list is refreshed from Git's tracked and non-ignored untracked files at startup. The system prompt now tells the model to consult that layout, batch independent reads/searches, combine bounded read-only exploration with the shell tool when useful, and group independent edits without adding planning turns to simple tasks.

The footer reports Gemini generation requests and tool calls for the current turn. `/context` reports generation requests and token usage for the current chat. These counters include retries, but do not include token-count/model metadata requests or separate web search requests. They count API calls, not billing tokens or cost.

## Call-count estimates from the request loop

These are code-path counts, not measurements from live user traffic:

| Scenario | Tool calls | Gemini generation requests |
|---|---:|---:|
| Direct answer, no tools | 0 | 1 |
| One response with two independent calls, then a final answer | 2 | 2 |
| Two dependent tool rounds, then a final answer | 2 | 3 |
| Any scenario with one retry | unchanged | add 1 |

The main potential reduction is encouraging Gemini to return independent operations together. The executor already supports this. It cannot collapse rounds where a later operation depends on an earlier result. Tool-call counts alone do not reveal API request counts; use the new request counter when comparing prompts.

## Follow-up measurement plan

For a before/after comparison, run the same representative tasks with the same model, repository snapshot, and prompt. Record footer tool calls and API requests, `/context` token totals, task completion, and whether the result needed correction. Include a direct answer, independent file discovery/read, a multi-file change, and a task with genuinely dependent steps. Repeat each task enough times to account for model variation. Keep retries and web search identifiable, since their quotas and behavior differ.

The local environment does not provide representative Gemini production traces, so no claim about average savings is made here. The current code path shows that batching can remove a model round trip per combined independent batch; it does not establish how often the model will batch in practice.

## Prioritized candidates

1. **Measure prompt guidance and current batching.** Compare the new guidance against the same tasks without it. Keep it only if it reduces generation requests without lowering completion quality.
2. **Keep startup context fresh at low cost.** The file list now refreshes at startup while the more expensive summary remains commit-cached. Measure startup overhead and whether it reduces discovery calls.
3. **Evaluate grouped edits and planning guidance.** Compare multi-file tasks and check request counts, correctness, and recovery after a failed edit. Avoid a separate planning round for simple work.
4. **Consider a multi-file patch tool only if measurements support it.** Compare it with the existing `write_file` and shell tools for request count, reliability, and reviewability.
5. **Defer local/alternate-model routing.** It adds provider and quality complexity and does not inherently reduce total API cost. Revisit only with measured cost and quality data.
