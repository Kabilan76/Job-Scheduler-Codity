import React, { useEffect, useState } from "react";
import { apiRequest } from "../utils/api";
import { Cpu, RefreshCw, AlertCircle, Play, Eye } from "lucide-react";

export default function WorkersPool({ onInspectJob }) {
  const [workers, setWorkers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const fetchWorkers = async () => {
    try {
      const res = await apiRequest("/dashboard/workers");
      if (!res.ok) throw new Error("Failed to load worker logs");
      const data = await res.json();
      setWorkers(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchWorkers();
    const interval = setInterval(fetchWorkers, 4000);
    return () => clearInterval(interval);
  }, []);

  const getStatusBadge = (worker) => {
    // Check if worker hasn't been seen in 30 seconds, mark as dead locally to stay real-time
    const lastSeen = new Date(worker.last_seen_at);
    const diff = (Date.now() - lastSeen) / 1000;
    
    if (diff > 30) {
      return <span className="badge badge-failed">Dead (Offline)</span>;
    }
    
    if (worker.status === "active") {
      return <span className="badge badge-completed">Active</span>;
    }
    return <span className="badge badge-queued">Inactive</span>;
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center h-[50vh] gap-3">
        <RefreshCw className="w-6 h-6 text-indigo-500 animate-spin" />
        <span className="text-slate-400 font-medium">Scanning cluster nodes...</span>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold flex items-center gap-2">
            <Cpu className="w-6 h-6 text-indigo-500" />
            Worker Pool Registry
          </h2>
          <p className="text-slate-400 text-sm mt-1">Audit active daemons participating in claiming locks</p>
        </div>
        <button
          onClick={fetchWorkers}
          className="p-2 glass-panel border border-slate-800 text-slate-400 hover:text-white"
        >
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {error && (
        <div className="p-4 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 flex items-start gap-3 text-sm">
          <AlertCircle className="w-5 h-5 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      <div className="glass-panel border border-slate-800 overflow-hidden">
        <table className="custom-table">
          <thead>
            <tr className="bg-slate-950/20">
              <th>Worker ID</th>
              <th>Hostname</th>
              <th>Status</th>
              <th>Current Lock (Job)</th>
              <th>Started At</th>
              <th>Last Heartbeat</th>
            </tr>
          </thead>
          <tbody>
            {workers.length === 0 ? (
              <tr>
                <td colSpan="6" className="text-center p-8 text-slate-500">
                  No workers currently connected to the coordinator registry. Start worker.py to join.
                </td>
              </tr>
            ) : (
              workers.map((worker) => (
                <tr key={worker.id}>
                  <td className="font-mono text-xs text-slate-400">
                    {worker.id}
                  </td>
                  <td className="font-semibold text-slate-200">
                    {worker.hostname}
                  </td>
                  <td>
                    {getStatusBadge(worker)}
                  </td>
                  <td>
                    {worker.current_job_id ? (
                      <button
                        onClick={() => onInspectJob(worker.current_job_id)}
                        className="text-xs font-semibold text-indigo-400 hover:text-indigo-300 inline-flex items-center gap-1"
                      >
                        <Eye className="w-3.5 h-3.5" /> {worker.current_job_id.substring(0, 8)}...
                      </button>
                    ) : (
                      <span className="text-xs text-slate-500 italic">Idle</span>
                    )}
                  </td>
                  <td className="text-xs text-slate-400">
                    {new Date(worker.started_at).toLocaleString()}
                  </td>
                  <td className="text-xs text-slate-400">
                    {new Date(worker.last_seen_at).toLocaleTimeString()}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
