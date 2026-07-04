import React, { useState } from "react";
import { setTokens } from "../utils/api";
import { KeyRound, Mail, User, ShieldAlert } from "lucide-react";

export default function Auth({ onAuthSuccess }) {
  const [isLogin, setIsLogin] = useState(true);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setLoading(true);

    const apiBase = import.meta.env.VITE_API_URL || "http://127.0.0.1:8001/api/v1";
    const endpoint = isLogin ? "/auth/login" : "/auth/register";
    const payload = isLogin ? { email, password } : { email, password, name };

    try {
      const res = await fetch(`${apiBase}${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || "Authentication failed");
      }

      if (isLogin) {
        const data = await res.json();
        setTokens(data.access_token, data.refresh_token);
        onAuthSuccess();
      } else {
        // Register successful, toggle to login
        setIsLogin(true);
        setError("Account created successfully! Please log in.");
      }
    } catch (err) {
      console.error("[Auth Failure]", err);
      if (err.message === "Failed to fetch") {
        setError("Network Error: Could not connect to the API server. Please ensure the backend is running at http://127.0.0.1:8001");
      } else {
        setError(err.message);
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-[#0b0f19] px-4">
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute top-[20%] left-[30%] w-[300px] h-[300px] bg-indigo-500/10 rounded-full blur-[120px]" />
        <div className="absolute bottom-[20%] right-[30%] w-[300px] h-[300px] bg-purple-500/10 rounded-full blur-[120px]" />
      </div>

      <div className="w-full max-w-md glass-panel p-8 shadow-2xl relative z-10">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold tracking-tight bg-gradient-to-r from-indigo-400 via-purple-400 to-pink-400 bg-clip-text text-transparent">
            Job Scheduler
          </h1>
          <p className="text-slate-400 text-sm mt-2">
            Distributed background execution engine
          </p>
        </div>

        <div className="flex border-b border-slate-800 mb-6">
          <button
            className={`flex-1 pb-3 text-sm font-semibold transition-all ${
              isLogin ? "border-b-2 border-indigo-500 text-indigo-400" : "text-slate-400"
            }`}
            onClick={() => {
              setIsLogin(true);
              setError("");
            }}
          >
            Log In
          </button>
          <button
            className={`flex-1 pb-3 text-sm font-semibold transition-all ${
              !isLogin ? "border-b-2 border-indigo-500 text-indigo-400" : "text-slate-400"
            }`}
            onClick={() => {
              setIsLogin(false);
              setError("");
            }}
          >
            Register
          </button>
        </div>

        {error && (
          <div className={`mb-6 p-4 rounded-lg flex items-start gap-3 text-sm ${
            error.includes("successfully") 
              ? "bg-emerald-500/10 border border-emerald-500/20 text-emerald-400" 
              : "bg-red-500/10 border border-red-500/20 text-red-400"
          }`}>
            <ShieldAlert className="w-5 h-5 shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-5">
          {!isLogin && (
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-semibold text-slate-400">Full Name</label>
              <div className="relative">
                <User className="absolute left-3 top-2.5 w-4 h-4 text-slate-500" />
                <input
                  type="text"
                  required
                  placeholder="John Doe"
                  className="w-full pl-10 pr-4 py-2"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </div>
            </div>
          )}

          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-semibold text-slate-400">Email Address</label>
            <div className="relative">
              <Mail className="absolute left-3 top-2.5 w-4 h-4 text-slate-500" />
              <input
                type="email"
                required
                placeholder="you@example.com"
                className="w-full pl-10 pr-4 py-2"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-semibold text-slate-400">Password</label>
            <div className="relative">
              <KeyRound className="absolute left-3 top-2.5 w-4 h-4 text-slate-500" />
              <input
                type="password"
                required
                placeholder="••••••••"
                className="w-full pl-10 pr-4 py-2"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 mt-2 bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-500 hover:to-purple-500 active:scale-[0.98] transition-all font-semibold rounded-lg shadow-lg shadow-indigo-600/15 disabled:opacity-50"
          >
            {loading ? "Please wait..." : isLogin ? "Access Dashboard" : "Create Account"}
          </button>
        </form>
      </div>
    </div>
  );
}
