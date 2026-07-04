import React, { useEffect, useState, useRef } from "react";
import { apiRequest, getWebSocketUrl } from "../utils/api";
import { 
  X, Terminal, Calendar, Award, Play, CheckCircle2, 
  AlertTriangle, Skull, RotateCcw, Copy, Activity 
} from "lucide-react";

export default function JobDetailModal({ jobId, onClose }) {
  const [job, setJob] = useState(null);
  const [executions, setExecutions] = useState([]);
  const [logs, setLogs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [retrying, setRetrying] = useState(false);
  const logsEndRef = useRef(null);

  const fetchData = async () => {
    try {
      // 1. Fetch Job Meta
      const jobRes = await apiRequest(`/jobs/${jobId}`);
      if (!jobRes.ok) throw new Error("Failed to load job details");
      const jobData = await jobRes.json();
      setJob(jobData);

      // 2. Fetch Executions
      const execRes = await apiRequest(`/jobs/${jobId}/executions`);
      if (execRes.ok) setExecutions(await execRes.json());

      // 3. Fetch Logs
      const logsRes = await apiRequest(`/jobs/${jobId}/logs`);
      if (logsRes.ok) setLogs(await logsRes.json());

    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (jobId) {
      fetchData();

      // Connect to WebSocket for real-time status and logs
      const wsUrl = getWebSocketUrl(`/ws/jobs/${jobId}/logs`);
      const ws = new WebSocket(wsUrl);

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          
          if (msg.type === "log_line") {
            setLogs(prev => {
              // Deduplicate logs just in case
              if (prev.some(l => l.ts === msg.ts && l.message === msg.message)) return prev;
              return [...prev, {
                ts: msg.ts,
                level: msg.level,
                message: msg.message
              }];
            });
          } else if (msg.type === "status_update") {
            // Re-fetch full details
            fetchData();
          }
        } catch (e) {
          // ignore
        }
      };

      ws.onerror = () => {
        console.warn("WebSocket logs streaming failed. Falling back to polling.");
      };

      // Poll fallback
      const interval = setInterval(fetchData, 4000);

      return () => {
        ws.close();
        clearInterval(interval);
      };
    }
  }, [jobId]);

  // Scroll logs console to bottom
  useEffect(() => {
    if (logsEndRef.current) {
      logsEndRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [logs]);

  const handleManualRetry = async () => {
    setRetrying(true);
    try {
      const res = await apiRequest(`/jobs/${jobId}/retry`, {
        method: "POST"
      });
      if (!res.ok) throw new Error("Retry request failed");
      await fetchData();
    } catch (err) {
      setError(err.message);
    } finally {
      setRetrying(false);
    }
  };

  const copyToClipboard = (text) => {
    navigator.clipboard.writeText(text);
  };

  if (loading) {
    return (
      <div className="fixed inset-0 bg-slate-950/70 backdrop-blur-sm z-50 flex items-center justify-center">
        <div className="glass-panel p-6 border border-slate-800 flex flex-col items-center gap-3">
          <Activity className="w-6 h-6 text-indigo-500 animate-spin" />
          <span className="text-slate-400 text-sm font-medium">Resolving record metadata...</span>
        </div>
      </div>
    );
  }

  if (!job) return null;

  return (
    <div className="fixed inset-0 bg-slate-950/80 backdrop-blur-sm z-50 flex items-center justify-center p-4 overflow-y-auto">
      <div className="w-full max-w-4xl glass-panel border border-slate-800 shadow-2xl relative z-10 flex flex-col max-h-[90vh]">
        
        {/* Modal Header */}
        <div className="p-6 border-b border-slate-800/80 bg-slate-950/20 flex items-center justify-between">
          <div>
            <div className="flex items-center gap-3">
              <h2 className="text-lg font-bold text-slate-200">Inspect Job</h2>
              <span className={`badge badge-${job.status}`}>{job.status.replace("_", " ")}</span>
            </div>
            <span className="text-xs text-slate-500 font-mono block mt-1 flex items-center gap-1.5">
              ID: {job.id} 
              <button 
                onClick={() => copyToClipboard(job.id)} 
                className="hover:text-slate-300 active:scale-95"
                title="Copy ID"
              >
                <Copy className="w-3 h-3" />
              </button>
            </span>
          </div>
          <button onClick={onClose} className="p-1 hover:bg-slate-800 rounded-lg text-slate-400">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-6 overflow-y-auto space-y-6 flex-1">
          {error && (
            <div className="p-4 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 text-sm">
              {error}
            </div>
          )}

          {/* Grid: Meta and Payload */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            
            {/* Meta List */}
            <div className="space-y-4">
              <h3 className="text-sm font-semibold text-slate-300 uppercase tracking-wider">Job Parameters</h3>
              <div className="grid grid-cols-2 gap-y-3 gap-x-2 text-xs border border-slate-800/60 p-4 rounded-lg bg-slate-950/10">
                <span className="text-slate-500">Pipeline Type:</span>
                <span className="font-semibold capitalize text-indigo-400">{job.type}</span>

                <span className="text-slate-500">Attempt Count:</span>
                <span className="font-semibold text-slate-300">{job.attempt_count} / {job.max_attempts}</span>

                <span className="text-slate-500">Scheduled Run:</span>
                <span className="font-mono text-slate-300">{new Date(job.run_at).toLocaleString()}</span>

                {job.idempotency_key && (
                  <>
                    <span className="text-slate-500">Idempotency Key:</span>
                    <span className="font-mono text-amber-400 truncate">{job.idempotency_key}</span>
                  </>
                )}

                {job.batch_id && (
                  <>
                    <span className="text-slate-500">Batch ID:</span>
                    <span className="font-mono text-pink-400 truncate">{job.batch_id}</span>
                  </>
                )}

                {job.cron_expression && (
                  <>
                    <span className="text-slate-500">Cron Rule:</span>
                    <span className="font-mono text-cyan-400">{job.cron_expression}</span>
                  </>
                )}

                {job.claimed_by && (
                  <>
                    <span className="text-slate-500">Running Worker:</span>
                    <span className="font-mono text-slate-300 truncate">{job.claimed_by}</span>
                  </>
                )}
              </div>

              {/* Action Buttons */}
              {(job.status === "dead_letter" || job.status === "failed") && (
                <button
                  onClick={handleManualRetry}
                  disabled={retrying}
                  className="w-full py-2 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white font-semibold text-sm rounded-lg active:scale-[0.98] transition-all flex items-center justify-center gap-2 disabled:opacity-50"
                >
                  <RotateCcw className="w-4 h-4" />
                  {retrying ? "Requeuing..." : "Manual Retry (Reset Attempts)"}
                </button>
              )}
            </div>

            {/* Payload JSON */}
            <div className="space-y-4 flex flex-col">
              <h3 className="text-sm font-semibold text-slate-300 uppercase tracking-wider">Original Payload</h3>
              <pre className="flex-1 bg-slate-900/80 border border-slate-800 p-4 rounded-lg font-mono text-xs text-indigo-300 overflow-auto max-h-[190px]">
                {JSON.stringify(job.payload, null, 2)}
              </pre>
            </div>

          </div>

          {/* Executions Attempts Table */}
          {executions.length > 0 && (
            <div className="space-y-3">
              <h3 className="text-sm font-semibold text-slate-300 uppercase tracking-wider">Execution Log history</h3>
              <div className="border border-slate-800/80 rounded-lg overflow-hidden">
                <table className="custom-table">
                  <thead className="bg-slate-950/20">
                    <tr>
                      <th>Attempt</th>
                      <th>Worker ID</th>
                      <th>Started At</th>
                      <th>Duration</th>
                      <th>Status</th>
                      <th>Error Context</th>
                    </tr>
                  </thead>
                  <tbody>
                    {executions.map((exec) => (
                      <tr key={exec.id}>
                        <td className="font-semibold text-slate-300">#{exec.attempt_number}</td>
                        <td className="font-mono text-xs text-slate-500">{exec.worker_id ? `${exec.worker_id.substring(0,8)}...` : "None"}</td>
                        <td className="text-xs text-slate-400">{new Date(exec.started_at).toLocaleTimeString()}</td>
                        <td className="text-xs text-slate-300">{exec.duration_ms ? `${exec.duration_ms} ms` : "-"}</td>
                        <td>
                          <span className={`badge badge-${exec.status}`}>{exec.status}</span>
                        </td>
                        <td className="text-xs text-red-400 font-mono max-w-[200px] truncate" title={exec.error_message}>
                          {exec.error_message || "-"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Live Streaming Logs Console */}
          <div className="space-y-3 flex flex-col">
            <h3 className="text-sm font-semibold text-slate-300 uppercase tracking-wider flex items-center gap-2">
              <Terminal className="w-4 h-4 text-indigo-400" />
              Standard Output Log Stream
            </h3>
            
            <div className="bg-[#040811] border border-slate-800/80 rounded-lg p-4 font-mono text-xs text-emerald-400 overflow-y-auto max-h-[220px] min-h-[140px] flex flex-col gap-1.5 shadow-inner">
              {logs.length === 0 ? (
                <span className="text-slate-600 italic">No console logs buffered for this execution run.</span>
              ) : (
                logs.map((log, idx) => (
                  <div key={idx} className="flex gap-3 leading-relaxed">
                    <span className="text-slate-600 shrink-0">[{new Date(log.ts).toLocaleTimeString()}]</span>
                    <span className={`shrink-0 font-semibold ${
                      log.level === "ERROR" ? "text-red-500" : log.level === "WARNING" ? "text-amber-500" : "text-sky-500"
                    }`}>
                      {log.level}
                    </span>
                    <span className="text-slate-300">{log.message}</span>
                  </div>
                ))
              )}
              <div ref={logsEndRef} />
            </div>
          </div>

        </div>
      </div>
    </div>
  );
}
