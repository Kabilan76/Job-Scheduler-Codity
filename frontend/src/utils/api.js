const BASE_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8001/api/v1";

export const getTokens = () => {
  const access = localStorage.getItem("access_token");
  const refresh = localStorage.getItem("refresh_token");
  return { access, refresh };
};

export const setTokens = (access, refresh) => {
  localStorage.setItem("access_token", access);
  localStorage.setItem("refresh_token", refresh);
};

export const clearTokens = () => {
  localStorage.removeItem("access_token");
  localStorage.removeItem("refresh_token");
};

// Queue to hold requests while refreshing
let isRefreshing = false;
let refreshSubscribers = [];

const subscribeTokenRefresh = (cb) => {
  refreshSubscribers.push(cb);
};

const onRefreshed = (token) => {
  refreshSubscribers.map((cb) => cb(token));
  refreshSubscribers = [];
};

export const apiRequest = async (endpoint, options = {}) => {
  const { access } = getTokens();
  
  const headers = {
    "Content-Type": "application/json",
    ...options.headers,
  };

  if (access) {
    headers["Authorization"] = `Bearer ${access}`;
  }

  const config = {
    ...options,
    headers,
  };

  const url = `${BASE_URL}${endpoint}`;
  let response;
  try {
    response = await fetch(url, config);
  } catch (err) {
    console.error(`[API Network Error] ${options.method || "GET"} ${url} failed:`, err);
    throw new Error("Network Error: Connection refused. Please ensure the backend is running at http://127.0.0.1:8001");
  }

  // Auto-refresh token if 401 Unauthorized
  if (response.status === 401 && !options._retry && !endpoint.includes("/auth/")) {
    if (isRefreshing) {
      return new Promise((resolve) => {
        subscribeTokenRefresh((token) => {
          config.headers["Authorization"] = `Bearer ${token}`;
          resolve(fetch(url, config));
        });
      });
    }

    options._retry = true;
    isRefreshing = true;

    try {
      const { refresh } = getTokens();
      if (!refresh) throw new Error("No refresh token");

      const refreshRes = await fetch(`${BASE_URL}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refresh }),
      });

      if (!refreshRes.ok) {
        clearTokens();
        window.location.reload();
        throw new Error("Refresh expired");
      }

      const data = await refreshRes.json();
      setTokens(data.access_token, data.refresh_token);
      
      isRefreshing = false;
      onRefreshed(data.access_token);

      // Retry original request
      config.headers["Authorization"] = `Bearer ${data.access_token}`;
      return fetch(url, config);
    } catch (err) {
      isRefreshing = false;
      clearTokens();
      throw err;
    }
  }

  return response;
};

export const getWebSocketUrl = (path) => {
  const wsProto = window.location.protocol === "https:" ? "wss:" : "ws:";
  // Check if base url is absolute, otherwise construct from current host
  if (BASE_URL.startsWith("http")) {
    const parsed = new URL(BASE_URL);
    return `${parsed.protocol === "https:" ? "wss:" : "ws:"}//${parsed.host}${parsed.pathname}${path}`;
  }
  return `${wsProto}//127.0.0.1:8001/api/v1${path}`;
};
