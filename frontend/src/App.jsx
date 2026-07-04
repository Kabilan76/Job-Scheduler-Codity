import React, { useEffect, useState } from "react";
import Auth from "./components/Auth";
import Dashboard from "./components/Dashboard";
import Queues from "./components/Queues";
import JobsExplorer from "./components/JobsExplorer";
import WorkersPool from "./components/WorkersPool";
import JobDetailModal from "./components/JobDetailModal";
import { getTokens, clearTokens, apiRequest } from "./utils/api";
import { 
  LayoutDashboard, FolderGit2, Layers, Cpu, LogOut, 
  Building2, Box, Menu, X, Terminal 
} from "lucide-react";

export default function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [activeTab, setActiveTab] = useState("dashboard");
  
  // Organization and Project States
  const [orgs, setOrgs] = useState([]);
  const [selectedOrg, setSelectedOrg] = useState(null);
  const [projects, setProjects] = useState([]);
  const [selectedProject, setSelectedProject] = useState(null);
  
  // Modal Inspect Job
  const [inspectJobId, setInspectJobId] = useState(null);
  
  // Mobile Sidebar Toggle
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const checkAuth = () => {
    const { access } = getTokens();
    setIsAuthenticated(!!access);
  };

  useEffect(() => {
    checkAuth();
  }, []);

  const fetchOrgsAndProjects = async () => {
    try {
      const orgsRes = await apiRequest("/organizations");
      if (!orgsRes.ok) throw new Error("Failed to load organizations");
      const orgsData = await orgsRes.ok ? await orgsRes.json() : [];
      setOrgs(orgsData);
      
      if (orgsData.length > 0) {
        const defaultOrg = orgsData[0];
        setSelectedOrg(defaultOrg);
        await loadProjectsForOrg(defaultOrg.id);
      }
    } catch (err) {
      console.error(err);
    }
  };

  const loadProjectsForOrg = async (orgId) => {
    try {
      const projRes = await apiRequest(`/projects?org_id=${orgId}`);
      if (projRes.ok) {
        const projData = await projRes.json();
        setProjects(projData);
        if (projData.length > 0) {
          setSelectedProject(projData[0]);
        } else {
          setSelectedProject(null);
        }
      }
    } catch (err) {
      console.error(err);
    }
  };

  useEffect(() => {
    if (isAuthenticated) {
      fetchOrgsAndProjects();
    }
  }, [isAuthenticated]);

  const handleOrgChange = async (orgId) => {
    const org = orgs.find(o => o.id === orgId);
    setSelectedOrg(org);
    await loadProjectsForOrg(orgId);
  };

  const handleSignOut = () => {
    clearTokens();
    setIsAuthenticated(false);
  };

  if (!isAuthenticated) {
    return <Auth onAuthSuccess={() => setIsAuthenticated(true)} />;
  }

  const renderContent = () => {
    if (!selectedProject) {
      return (
        <div className="flex flex-col items-center justify-center h-[70vh] gap-3">
          <Terminal className="w-8 h-8 text-indigo-500" />
          <span className="text-slate-400 font-medium">Please register a project to begin.</span>
        </div>
      );
    }

    switch (activeTab) {
      case "dashboard":
        return <Dashboard projectId={selectedProject.id} />;
      case "queues":
        return <Queues projectId={selectedProject.id} />;
      case "jobs":
        return <JobsExplorer projectId={selectedProject.id} onInspectJob={(id) => setInspectJobId(id)} />;
      case "workers":
        return <WorkersPool onInspectJob={(id) => setInspectJobId(id)} />;
      default:
        return <Dashboard projectId={selectedProject.id} />;
    }
  };

  const navItems = [
    { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
    { id: "queues", label: "Queues & Concurrency", icon: FolderGit2 },
    { id: "jobs", label: "Jobs Explorer", icon: Layers },
    { id: "workers", label: "Workers Pool", icon: Cpu },
  ];

  return (
    <div className="min-h-screen bg-[#0b0f19] flex">
      {/* Background glow */}
      <div className="fixed inset-0 overflow-hidden pointer-events-none z-0">
        <div className="absolute top-0 right-1/4 w-[500px] h-[500px] bg-indigo-500/5 rounded-full blur-[160px]" />
        <div className="absolute bottom-0 left-1/4 w-[500px] h-[500px] bg-purple-500/5 rounded-full blur-[160px]" />
      </div>

      {/* Sidebar - Desktop */}
      <aside className={`fixed inset-y-0 left-0 z-40 w-64 glass-panel border-r border-slate-800/80 p-6 flex flex-col justify-between transform md:translate-x-0 transition-transform duration-200 ${
        sidebarOpen ? "translate-x-0" : "-translate-x-full"
      } md:relative md:z-10 bg-[#0c1221]`}>
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <h1 className="text-lg font-bold bg-gradient-to-r from-indigo-400 to-purple-400 bg-clip-text text-transparent">
              Coordinator Panel
            </h1>
            <button onClick={() => setSidebarOpen(false)} className="md:hidden p-1 text-slate-400">
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* Org & Project Selector */}
          <div className="space-y-3 pt-4 border-t border-slate-800/60">
            <div className="flex flex-col gap-1">
              <span className="text-[10px] text-slate-500 uppercase font-bold tracking-wider flex items-center gap-1">
                <Building2 className="w-3 h-3" /> Organization
              </span>
              <select
                className="bg-slate-900 border-slate-800 text-xs py-1.5"
                value={selectedOrg?.id || ""}
                onChange={(e) => handleOrgChange(e.target.value)}
              >
                {orgs.map((org) => (
                  <option key={org.id} value={org.id}>{org.name}</option>
                ))}
              </select>
            </div>

            <div className="flex flex-col gap-1">
              <span className="text-[10px] text-slate-500 uppercase font-bold tracking-wider flex items-center gap-1">
                <Box className="w-3 h-3" /> Project
              </span>
              <select
                className="bg-slate-900 border-slate-800 text-xs py-1.5"
                value={selectedProject?.id || ""}
                onChange={(e) => setSelectedProject(projects.find(p => p.id === e.target.value))}
              >
                {projects.map((proj) => (
                  <option key={proj.id} value={proj.id}>{proj.name}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Navigation Links */}
          <nav className="space-y-1.5 pt-4">
            {navItems.map((item) => (
              <button
                key={item.id}
                onClick={() => {
                  setActiveTab(item.id);
                  setSidebarOpen(false);
                }}
                className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-semibold transition-all ${
                  activeTab === item.id
                    ? "bg-indigo-600/10 text-indigo-400 border border-indigo-500/15"
                    : "text-slate-400 hover:bg-slate-900/50 hover:text-slate-200 border border-transparent"
                }`}
              >
                <item.icon className="w-4 h-4" />
                {item.label}
              </button>
            ))}
          </nav>
        </div>

        {/* User profile / Logout */}
        <div className="pt-4 border-t border-slate-800/60 flex items-center justify-between">
          <div className="flex flex-col">
            <span className="text-xs text-slate-400 font-semibold truncate max-w-[120px]">Job Scheduler Dev</span>
          </div>
          <button 
            onClick={handleSignOut} 
            className="p-1.5 hover:bg-red-500/10 text-slate-500 hover:text-red-400 rounded-lg transition-all"
            title="Sign Out"
          >
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </aside>

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0 z-10 relative">
        {/* Mobile Header */}
        <header className="md:hidden glass-panel border-b border-slate-800/80 p-4 flex items-center justify-between">
          <span className="font-bold text-indigo-400">Coordinator</span>
          <button onClick={() => setSidebarOpen(true)} className="p-1 text-slate-400">
            <Menu className="w-6 h-6" />
          </button>
        </header>

        {/* Tab Wrapper */}
        <main className="p-6 md:p-8 flex-1 max-w-7xl w-full mx-auto">
          {renderContent()}
        </main>
      </div>

      {/* Inspection Modal */}
      {inspectJobId && (
        <JobDetailModal 
          jobId={inspectJobId} 
          onClose={() => setInspectJobId(null)} 
        />
      )}
    </div>
  );
}
