import React, { useEffect, useState } from "react";
import { apiRequest } from "../utils/api";
import { 
  Play, Filter, Layers, RefreshCw, ChevronLeft, ChevronRight, 
  Terminal, Search, Eye, AlertCircle, Plus 
} from "lucide-react";

export default function JobsExplorer({ projectId, onInspectJob }) {
  const [jobs, setJobs] = useState([]);
  const [queues, setQueues] = useState([]);
  const [policies, setPolicies] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Filters
  const [selectedQueue, setSelectedQueue] = useState("");
  const [selectedStatus, setSelectedStatus] = useState("");
  const [page, setPage] = useState(1);
  const pageSize = 15;

  // Trigger Job Form State
  const [showTriggerForm, setShowTriggerForm] = useState(false);
  const [formQueue, setFormQueue] = useState("");
  const [formType, setFormType] = useState("immediate");
  const [formPayload, setFormPayload] = useState('{"action": "success", "duration": 2}');
  const [formPriority, setFormPriority] = useState(0);
  const [formIdempotency, setFormIdempotency] = useState("");
  const [formCron, setFormCron] = useState("*/1 * * * *");
  const [formDelay, setFormDelay] = useState(10);
  const [formDeps, setFormDeps] = useState("");
  const [formPolicy, setFormPolicy] = useState("");
  const [formMaxAttempts, setFormMaxAttempts] = useState(3);
  const [submitting, setSubmitting] = useState(false);

  const fetchJobs = async () => {
    try {
      let url = `/jobs?project_id=${projectId}&page=${page}&page_size=${pageSize}`;
      if (selectedQueue) url += `&queue_id=${selectedQueue}`;
      if (selectedStatus) url += `&status=${selectedStatus}`;

      const res = await apiRequest(url);
      if (!res.ok) throw new Error("Failed to load jobs");
      const data = await res.json();
      setJobs(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const fetchFilters = async () => {
    try {
      const qRes = await apiRequest(`/queues?project_id=${projectId}`);
      if (qRes.ok) {
        const qData = await qRes.json();
        setQueues(qData);
        if (qData.length > 0) setFormQueue(qData[0].id);
      }

      const pRes = await apiRequest(`/retry-policies`);
      if (pRes.ok) {
        setPolicies(await pRes.json());
      }
    } catch (err) {
      // silent fail
    }
  };

  useEffect(() => {
    if (projectId) {
      fetchJobs();
    }
  }, [projectId, selectedQueue, selectedStatus, page]);

  useEffect(() => {
    if (projectId) {
      fetchFilters();
    }
  }, [projectId]);

  const handleTriggerJob = async (e) => {
    e.preventDefault();
    setError("");
    setSubmitting(true);

    try {
      let payloadParsed = {};
      try {
        payloadParsed = JSON.parse(formPayload);
      } catch (err) {
        throw new Error("Payload must be valid JSON");
      }

      // Calculate run_at for delayed jobs
      let runAt = null;
      if (formType === "delayed") {
        runAt = new Date(Date.now() + formDelay * 1000).toISOString();
      }

      // Calculate batch items if type is batch
      if (formType === "batch") {
        if (!payloadParsed.jobs || !Array.isArray(payloadParsed.jobs)) {
          // If not provided in payload, auto-generate 3 simple jobs
          payloadParsed = {
            jobs: [
              { payload: { action: "success", duration: 2, subjob: 1 } },
              { payload: { action: "fail", error_message: "Sub-job 2 crashed!", duration: 1, subjob: 2 } },
              { payload: { action: "success", duration: 3, subjob: 3 } }
            ]
          };
        }
      }

      const dependsOn = formDeps
        ? formDeps.split(",").map(id => id.trim()).filter(id => id.length > 0)
        : [];

      const body = {
        queue_id: formQueue,
        project_id: projectId,
        type: formType,
        payload: payloadParsed,
        priority: parseInt(formPriority),
        idempotency_key: formIdempotency || null,
        depends_on_ids: dependsOn,
        retry_policy_id: formPolicy || null,
        max_attempts: parseInt(formMaxAttempts),
        run_at: runAt,
        cron_expression: (formType === "scheduled" || formType === "recurring") ? formCron : null
      };

      const res = await apiRequest("/jobs", {
        method: "POST",
        body: JSON.stringify(body)
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || "Failed to trigger job");
      }

      setShowTriggerForm(false);
      setFormIdempotency("");
      setFormDeps("");
      setPage(1);
      fetchJobs();
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  const getStatusBadge = (status) => {
    return <span className={`badge badge-${status}`}>{status.replace("_", " ")}</span>;
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold flex items-center gap-2">
            <Layers className="w-6 h-6 text-indigo-500" />
            Jobs & Workflows Explorer
          </h2>
          <p className="text-slate-400 text-sm mt-1">Audit, trace, and debug executions in this workspace</p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={() => setShowTriggerForm(!showTriggerForm)}
            className="flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-500 font-semibold text-sm rounded-lg active:scale-[0.98] transition-all"
          >
            <Plus className="w-4 h-4" /> Trigger New Job
          </button>
          <button
            onClick={fetchJobs}
            className="p-2 glass-panel border border-slate-800 text-slate-400 hover:text-white"
            title="Reload table"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {error && (
        <div className="p-4 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 flex items-start gap-3 text-sm">
          <AlertCircle className="w-5 h-5 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {/* Trigger Form Panel */}
      {showTriggerForm && (
        <div className="glass-panel p-6 border border-indigo-500/20 space-y-6 relative">
          <div>
            <h3 className="text-md font-semibold text-slate-200">Submit New Job Payload</h3>
            <p className="text-slate-400 text-xs mt-1">Specify parameters to inject into the job pipeline</p>
          </div>

          <form onSubmit={handleTriggerJob} className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div className="space-y-4">
              <div className="flex flex-col gap-1.5">
                <label className="text-xs text-slate-400 font-semibold">Queue Pipeline</label>
                <select required value={formQueue} onChange={e => setFormQueue(e.target.value)}>
                  {queues.map(q => <option key={q.id} value={q.id}>{q.name}</option>)}
                </select>
              </div>

              <div className="flex flex-col gap-1.5">
                <label className="text-xs text-slate-400 font-semibold">Job Type</label>
                <select value={formType} onChange={e => setFormType(e.target.value)}>
                  <option value="immediate">Immediate</option>
                  <option value="delayed">Delayed (Future Timestamp)</option>
                  <option value="scheduled">Scheduled (Cron Expression)</option>
                  <option value="recurring">Recurring (Periodic Cron)</option>
                  <option value="batch">Batch (Child Job Collection)</option>
                </select>
              </div>

              {formType === "delayed" && (
                <div className="flex flex-col gap-1.5">
                  <label className="text-xs text-slate-400 font-semibold">Delay (Seconds)</label>
                  <input type="number" min="1" value={formDelay} onChange={e => setFormDelay(e.target.value)} />
                </div>
              )}

              {(formType === "scheduled" || formType === "recurring") && (
                <div className="flex flex-col gap-1.5">
                  <label className="text-xs text-slate-400 font-semibold">Cron Expression</label>
                  <input type="text" placeholder="*/5 * * * *" value={formCron} onChange={e => setFormCron(e.target.value)} />
                </div>
              )}
            </div>

            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="flex flex-col gap-1.5">
                  <label className="text-xs text-slate-400 font-semibold">Priority</label>
                  <input type="number" value={formPriority} onChange={e => setFormPriority(e.target.value)} />
                </div>
                <div className="flex flex-col gap-1.5">
                  <label className="text-xs text-slate-400 font-semibold">Max Attempts</label>
                  <input type="number" min="1" value={formMaxAttempts} onChange={e => setFormMaxAttempts(e.target.value)} />
                </div>
              </div>

              <div className="flex flex-col gap-1.5">
                <label className="text-xs text-slate-400 font-semibold">Idempotency Key</label>
                <input 
                  type="text" 
                  placeholder="e.g. order_3948_check" 
                  value={formIdempotency} 
                  onChange={e => setFormIdempotency(e.target.value)} 
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <label className="text-xs text-slate-400 font-semibold">Retry Policy</label>
                <select value={formPolicy} onChange={e => setFormPolicy(e.target.value)}>
                  <option value="">None (Fail Immediately)</option>
                  {policies.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                </select>
              </div>
            </div>

            <div className="space-y-4">
              <div className="flex flex-col gap-1.5 h-full">
                <label className="text-xs text-slate-400 font-semibold">Payload JSON</label>
                <textarea
                  className="flex-1 font-mono text-xs bg-slate-900/60 border border-slate-800 p-2 rounded-lg outline-none focus:border-indigo-500 min-h-[100px]"
                  value={formPayload}
                  onChange={e => setFormPayload(e.target.value)}
                />
              </div>
            </div>

            <div className="md:col-span-3 flex justify-end gap-3 border-t border-slate-800 pt-4 mt-2">
              <div className="flex-1 flex flex-col gap-1.5 pr-8">
                <label className="text-xs text-slate-500 font-semibold">Dependencies (Comma-separated Job IDs, Optional)</label>
                <input 
                  type="text" 
                  className="py-1 text-xs" 
                  placeholder="UUID-1, UUID-2" 
                  value={formDeps} 
                  onChange={e => setFormDeps(e.target.value)} 
                />
              </div>
              <button
                type="button"
                onClick={() => setShowTriggerForm(false)}
                className="px-4 py-2 border border-slate-800 hover:bg-slate-800 rounded-lg text-sm text-slate-400"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={submitting}
                className="px-6 py-2 bg-indigo-600 hover:bg-indigo-500 font-semibold text-sm rounded-lg active:scale-[0.98] transition-all disabled:opacity-50"
              >
                {submitting ? "Triggering..." : "Submit Job"}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Filter and Listing Panel */}
      <div className="glass-panel border border-slate-800 overflow-hidden">
        {/* Filters Header */}
        <div className="p-4 border-b border-slate-800/80 bg-slate-950/20 flex flex-wrap items-center justify-between gap-4">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-2 text-xs text-slate-400 font-semibold">
              <Filter className="w-3.5 h-3.5" /> Filter by:
            </div>
            
            <select
              className="text-xs bg-slate-900/80 border-slate-800 py-1"
              value={selectedQueue}
              onChange={(e) => { setSelectedQueue(e.target.value); setPage(1); }}
            >
              <option value="">All Queues</option>
              {queues.map(q => <option key={q.id} value={q.id}>{q.name}</option>)}
            </select>

            <select
              className="text-xs bg-slate-900/80 border-slate-800 py-1"
              value={selectedStatus}
              onChange={(e) => { setSelectedStatus(e.target.value); setPage(1); }}
            >
              <option value="">All Statuses</option>
              <option value="queued">Queued</option>
              <option value="scheduled">Scheduled</option>
              <option value="claimed">Claimed</option>
              <option value="running">Running</option>
              <option value="completed">Completed</option>
              <option value="failed">Failed</option>
              <option value="dead_letter">Dead Letter</option>
            </select>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={page === 1}
              className="p-1 glass-card border border-slate-800 disabled:opacity-30"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <span className="text-xs text-slate-400">Page {page}</span>
            <button
              onClick={() => setPage(p => p + 1)}
              disabled={jobs.length < pageSize}
              className="p-1 glass-card border border-slate-800 disabled:opacity-30"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Jobs Table */}
        <div className="overflow-x-auto">
          {loading ? (
            <div className="p-12 text-center text-slate-500">Scanning task registry...</div>
          ) : jobs.length === 0 ? (
            <div className="p-12 text-center text-slate-500">No jobs match the current filters.</div>
          ) : (
            <table className="custom-table">
              <thead>
                <tr>
                  <th>Job ID</th>
                  <th>Queue</th>
                  <th>Type</th>
                  <th>Payload Preview</th>
                  <th>Status</th>
                  <th>Attempts</th>
                  <th>Run At</th>
                  <th className="text-right">Actions</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((job) => (
                  <tr key={job.id}>
                    <td className="font-mono text-xs text-slate-400">
                      {job.id.substring(0, 8)}...
                    </td>
                    <td>
                      {queues.find(q => q.id === job.queue_id)?.name || "Default"}
                    </td>
                    <td>
                      <span className="text-xs font-semibold capitalize text-indigo-400">{job.type}</span>
                    </td>
                    <td className="font-mono text-xs text-slate-500 max-w-[200px] truncate">
                      {JSON.stringify(job.payload)}
                    </td>
                    <td>
                      {getStatusBadge(job.status)}
                    </td>
                    <td className="text-xs font-medium text-slate-300">
                      {job.attempt_count} / {job.max_attempts}
                    </td>
                    <td className="text-xs text-slate-400">
                      {new Date(job.run_at).toLocaleTimeString()}
                    </td>
                    <td className="text-right">
                      <button
                        onClick={() => onInspectJob(job.id)}
                        className="p-1 text-slate-400 hover:text-white inline-flex items-center gap-1.5 text-xs font-semibold glass-card px-2.5 py-1 border border-slate-800"
                      >
                        <Eye className="w-3.5 h-3.5" /> Inspect
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  );
}
