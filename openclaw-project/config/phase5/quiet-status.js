// Native automation script: one read-only status call, no model or delivery.
// toolsAllow must be exactly ["session_status"] and toolBudget must be 1.
const result = await tools.session_status({});
if (!result || result.isError) {
  throw new Error("The native session status check was unavailable.");
}
return {
  state: {
    schemaVersion: 1,
    check: "session_status",
    lastCheckedAt: new Date().toISOString(),
    result: "ok"
  }
};
