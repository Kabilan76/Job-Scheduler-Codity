import React, { useEffect, useState } from "react";
import { apiRequest, getWebSocketUrl } from "../utils/api";
import { 
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer 
} from "recharts";
import { 
  LayoutDashboard, Play, CheckCircle2, AlertTriangle, Skull, 
  Users, Activity, Timer, RotateCw, Hourglass 
} from "lucide-react";

export default function Dashboard({ projectId }) {
  const [metrics, setMetrics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const fetchMetrics = async () => {
    try {
      const res = await apiRequest(`/dashboard/metrics?project_id=${projectId}`);
      if (!res.ok) throw new Error("Failed to load metrics");
      const data = await res.json();
      setMetrics(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!projectId) return;
    
    // Initial fetch
    fetchMetrics();

    // Setup Websocket for Real-Time Updates
    const wsUrl = getWebSocketUrl(`/ws/dashboard?project_id=${projectId}`);
    const ws = new WebSocket(wsUrl);

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === "dashboard_refresh") {
          // Re-fetch metrics
          fetchMetrics();
        }
      } catch (e) {
        // ignore
      }
    };

    ws.onerror = () => {
      console.warn("WebSocket dashboard connection failed. Falling back to polling.");
    };

    // Polling fallback
    const interval = setInterval(fetchMetrics, 5000);

    return () => {
      ws.close();
      clearInterval(interval);
    };
  }, [projectId]);

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center h-[60vh] gap-3">
        <RotateCw className="w-8 h-8 text-indigo-500 animate-spin" />
        <span className="text-slate-400 font-medium">Analyzing engine state...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 glass-panel border border-red-500/20 text-red-400">
        Error loading metrics: {error}
      </div>
    );
  }

  const { status_counts, active_workers_count, avg_execution_time_ms, throughput_series } = metrics;

  const cardData = [
    { label: "Queued", value: status_counts.queued, icon: Hourglass, color: "text-slate-400 border-slate-500/10 bg-slate-500/5" },
    { label: "Scheduled", value: status_counts.scheduled, icon: Timer, color: "text-sky-400 border-sky-500/10 bg-sky-500/5" },
    { label: "Running", value: status_counts.running + status_counts.claimed, icon: Play, color: "text-orange-400 border-orange-500/10 bg-orange-500/5" },
    { label: "Completed", value: status_counts.completed, icon: CheckCircle2, color: "text-emerald-400 border-emerald-500/10 bg-emerald-500/5" },
    { label: "Failed", value: status_counts.failed, icon: AlertTriangle, color: "text-red-400 border-red-500/10 bg-red-500/5" },
    { label: "Dead Letter", value: status_counts.dead_letter, icon: Skull, color: "text-purple-400 border-purple-500/10 bg-purple-500/5" },
  ];

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold flex items-center gap-2">
            <LayoutDashboard className="w-6 h-6 text-indigo-500" />
            Dashboard Overview
          </h2>
          <p className="text-slate-400 text-sm mt-1">Real-time state of the scheduler worker pool</p>
        </div>
        <button 
          onClick={fetchMetrics} 
          className="flex items-center gap-2 px-3 py-1.5 glass-panel text-sm text-slate-300 hover:text-white"
        >
          <RotateCw className="w-4 h-4" /> Refresh
        </button>
      </div>

      {/* Grid Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-6 gap-4">
        {cardData.map((card, idx) => (
          <div key={idx} className={`glass-card p-5 border ${card.color} flex flex-col gap-3`}>
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wider">{card.label}</span>
              <card.icon className="w-5 h-5 opacity-80" />
            </div>
            <span className="text-3xl font-bold tracking-tight">{card.value}</span>
          </div>
        ))}
      </div>

      {/* Auxiliary Metrics & Chart */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Workers & Average Time */}
        <div className="flex flex-col gap-4">
          <div className="glass-card p-6 border border-indigo-500/10 flex items-center justify-between">
            <div>
              <span className="text-slate-400 text-xs font-semibold uppercase tracking-wider block">Active Workers</span>
              <span className="text-4xl font-bold tracking-tight block mt-1">{active_workers_count}</span>
            </div>
            <div className="p-3 bg-indigo-500/10 text-indigo-400 rounded-lg">
              <Users className="w-6 h-6" />
            </div>
          </div>

          <div className="glass-card p-6 border border-purple-500/10 flex items-center justify-between">
            <div>
              <span className="text-slate-400 text-xs font-semibold uppercase tracking-wider block">Avg Execution Time</span>
              <span className="text-4xl font-bold tracking-tight block mt-1">
                {avg_execution_time_ms.toLocaleString()} <span className="text-sm font-medium text-slate-500">ms</span>
              </span>
            </div>
            <div className="p-3 bg-purple-500/10 text-purple-400 rounded-lg">
              <Activity className="w-6 h-6" />
            </div>
          </div>
        </div>

        {/* Throughput Chart */}
        <div className="lg:col-span-2 glass-panel p-6 border border-slate-800 flex flex-col gap-4">
          <div>
            <h3 className="text-md font-semibold text-slate-200">Throughput (Completed/Hr)</h3>
            <span className="text-slate-500 text-xs">Past 12 hours timeline</span>
          </div>
          <div className="h-[200px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={throughput_series} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                <defs>
                  <linearGradient id="colorThroughput" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#6366f1" stopOpacity={0.2}/>
                    <stop offset="95%" stopColor="#6366f1" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                <XAxis dataKey="time" stroke="#64748b" fontSize={11} tickLine={false} />
                <YAxis stroke="#64748b" fontSize={11} tickLine={false} />
                <Tooltip 
                  contentStyle={{ backgroundColor: "#0f172a", border: "1px solid rgba(255,255,255,0.1)", borderRadius: "8px" }} 
                  labelStyle={{ color: "#94a3b8" }}
                />
                <Area type="monotone" dataKey="completed" name="Completed Jobs" stroke="#6366f1" strokeWidth={2} fillOpacity={1} fill="url(#colorThroughput)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>
    </div>
  );
}
