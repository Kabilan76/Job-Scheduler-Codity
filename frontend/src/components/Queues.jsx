import React, { useEffect, useState } from "react";
import { apiRequest } from "../utils/api";
import { 
  FolderGit2, Plus, Play, Pause, AlertCircle, RefreshCw, 
  Settings2, HelpCircle 
} from "lucide-react";

export default function Queues({ projectId }) {
  const [queues, setQueues] = useState([]);
  const [policies, setPolicies] = useState([]);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  // Form State
  const [name, setName] = useState("");
  const [priority, setPriority] = useState(0);
  const [maxConcurrency, setMaxConcurrency] = useState(1);
  const [policyId, setPolicyId] = useState("");

  const fetchData = async () => {
    try {
      const queuesRes = await apiRequest(`/queues/stats?project_id=${projectId}`);
      if (!queuesRes.ok) throw new Error("Failed to fetch queues");
      const queuesData = await queuesRes.json();
      setQueues(queuesData);

      const policiesRes = await apiRequest(`/retry-policies`);
      if (policiesRes.ok) {
        const policiesData = await policiesRes.json();
        setPolicies(policiesData);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (projectId) {
      fetchData();
    }
  }, [projectId]);

  const handleCreateQueue = async (e) => {
    e.preventDefault();
    setError("");
    setSubmitting(true);

    try {
      const payload = {
        project_id: projectId,
        name,
        priority: parseInt(priority),
        max_concurrency: parseInt(maxConcurrency),
        default_retry_policy_id: policyId || null,
      };

      const res = await apiRequest("/queues", {
        method: "POST",
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || "Failed to create queue");
      }

      // Reset form and reload
      setName("");
      setPriority(0);
      setMaxConcurrency(1);
      setPolicyId("");
      fetchData();
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  const handleTogglePause = async (queueId, isPaused) => {
    try {
      const action = isPaused ? "resume" : "pause";
      const res = await apiRequest(`/queues/${queueId}/${action}`, {
        method: "POST",
      });
      if (!res.ok) throw new Error(`Failed to ${action} queue`);
      
      // Update queue locally to avoid full reload flicker
      setQueues(queues.map(q => q.id === queueId ? { ...q, is_paused: !isPaused } : q));
      fetchData(); // pull latest stats
    } catch (err) {
      setError(err.message);
    }
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center h-[50vh] gap-3">
        <RefreshCw className="w-6 h-6 text-indigo-500 animate-spin" />
        <span className="text-slate-400 font-medium">Scanning queues...</span>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-2xl font-bold flex items-center gap-2">
          <FolderGit2 className="w-6 h-6 text-indigo-500" />
          Queues & Concurrency
        </h2>
        <p className="text-slate-400 text-sm mt-1">Configure isolation barriers and rate limits for job streams</p>
      </div>

      {error && (
        <div className="p-4 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 flex items-start gap-3 text-sm">
          <AlertCircle className="w-5 h-5 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-8">
        {/* List of Queues */}
        <div className="xl:col-span-2 space-y-4">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-md font-semibold text-slate-300">Active Queue Pipelines</h3>
            <span className="text-xs text-slate-500">{queues.length} Total</span>
          </div>

          {queues.length === 0 ? (
            <div className="glass-panel p-8 text-center text-slate-500 border border-dashed border-slate-800">
              No queues registered for this project. Create one on the right to start executing jobs.
            </div>
          ) : (
            queues.map((queue) => (
              <div 
                key={queue.id} 
                className={`glass-card p-6 border ${
                  queue.is_paused 
                    ? "border-amber-500/10 bg-amber-500/5 opacity-80" 
                    : "border-slate-800"
                } flex flex-col md:flex-row md:items-center justify-between gap-6`}
              >
                <div className="space-y-2">
                  <div className="flex items-center gap-3">
                    <span className="text-lg font-bold text-slate-200">{queue.name}</span>
                    {queue.is_paused ? (
                      <span className="badge badge-failed">Paused</span>
                    ) : (
                      <span className="badge badge-completed">Active</span>
                    )}
                  </div>
                  <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-400">
                    <span>Priority: <strong className="text-slate-200">{queue.priority}</strong></span>
                    <span>Max Concurrency: <strong className="text-slate-200">{queue.max_concurrency}</strong></span>
                    {queue.default_retry_policy_id && (
                      <span>Default Policy: <strong className="text-indigo-400">
                        {policies.find(p => p.id === queue.default_retry_policy_id)?.name || "Custom"}
                      </strong></span>
                    )}
                  </div>
                </div>

                {/* Queue Job Stats */}
                <div className="flex items-center gap-4 border-l border-slate-800/50 pl-0 md:pl-6">
                  <div className="text-center px-3">
                    <span className="text-xs text-slate-500 uppercase block">Queued</span>
                    <span className="text-lg font-bold text-slate-300">{queue.stats.queued}</span>
                  </div>
                  <div className="text-center px-3">
                    <span className="text-xs text-slate-500 uppercase block">Running</span>
                    <span className="text-lg font-bold text-orange-400">{queue.stats.running}</span>
                  </div>
                  <div className="text-center px-3">
                    <span className="text-xs text-slate-500 uppercase block">Completed</span>
                    <span className="text-lg font-bold text-emerald-400">{queue.stats.completed}</span>
                  </div>
                  <div className="text-center px-3">
                    <span className="text-xs text-slate-500 uppercase block">Failed</span>
                    <span className="text-lg font-bold text-red-400">{queue.stats.failed}</span>
                  </div>
                  <div className="text-center px-3 border-l border-slate-800/50">
                    <span className="text-xs text-indigo-400 uppercase block">Workers</span>
                    <span className="text-lg font-bold text-indigo-400">{queue.stats.active_workers}</span>
                  </div>
                </div>

                {/* Actions */}
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => handleTogglePause(queue.id, queue.is_paused)}
                    className={`p-2 rounded-lg border transition-all ${
                      queue.is_paused 
                        ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-400 hover:bg-emerald-500/20"
                        : "bg-amber-500/10 border-amber-500/20 text-amber-400 hover:bg-amber-500/20"
                    }`}
                    title={queue.is_paused ? "Resume Queue" : "Pause Queue"}
                  >
                    {queue.is_paused ? <Play className="w-4 h-4" /> : <Pause className="w-4 h-4" />}
                  </button>
                </div>
              </div>
            ))
          )}
        </div>

        {/* Create Queue Panel */}
        <div className="glass-panel p-6 border border-slate-800 h-fit space-y-6">
          <div>
            <h3 className="text-md font-semibold text-slate-200">Register New Queue</h3>
            <p className="text-slate-400 text-xs mt-1">Isolate task threads under a specific SLA rule</p>
          </div>

          <form onSubmit={handleCreateQueue} className="space-y-4">
            <div className="flex flex-col gap-1.5">
              <label className="text-xs text-slate-400 font-semibold">Queue Name</label>
              <input
                type="text"
                required
                placeholder="e.g. email-delivery-queue"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="flex flex-col gap-1.5">
                <label className="text-xs text-slate-400 font-semibold">Priority</label>
                <input
                  type="number"
                  required
                  min="-100"
                  max="100"
                  value={priority}
                  onChange={(e) => setPriority(e.target.value)}
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <label className="text-xs text-slate-400 font-semibold">Max Concurrency</label>
                <input
                  type="number"
                  required
                  min="1"
                  max="50"
                  value={maxConcurrency}
                  onChange={(e) => setMaxConcurrency(e.target.value)}
                />
              </div>
            </div>

            <div className="flex flex-col gap-1.5">
              <label className="text-xs text-slate-400 font-semibold">Default Retry Policy</label>
              <select
                value={policyId}
                onChange={(e) => setPolicyId(e.target.value)}
              >
                <option value="">None (Fail Immediately)</option>
                {policies.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} ({p.strategy} - max {p.max_retries} retries)
                  </option>
                ))}
              </select>
            </div>

            <button
              type="submit"
              disabled={submitting}
              className="w-full py-2 bg-indigo-600 hover:bg-indigo-500 font-semibold text-sm rounded-lg active:scale-[0.98] transition-all disabled:opacity-50 flex items-center justify-center gap-2 mt-2"
            >
              <Plus className="w-4 h-4" />
              {submitting ? "Creating..." : "Create Queue"}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
