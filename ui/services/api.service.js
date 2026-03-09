// Dịch vụ API cho Giao diện WiFi-DensePose

import { API_CONFIG, buildApiUrl } from '../config/api.config.js';
import { backendDetector } from '../utils/backend-detector.js';

export class ApiService {
  constructor() {
    this.authToken = null;
    this.requestInterceptors = [];
    this.responseInterceptors = [];
  }

  // Đặt token xác thực
  setAuthToken(token) {
    this.authToken = token;
  }

  // Thêm bộ chặn yêu cầu
  addRequestInterceptor(interceptor) {
    this.requestInterceptors.push(interceptor);
  }

  // Thêm bộ chặn phản hồi
  addResponseInterceptor(interceptor) {
    this.responseInterceptors.push(interceptor);
  }

  // Xây dựng tiêu đề cho yêu cầu
  getHeaders(customHeaders = {}) {
    const headers = {
      ...API_CONFIG.DEFAULT_HEADERS,
      ...customHeaders
    };

    if (this.authToken) {
      headers['Authorization'] = `Bearer ${this.authToken}`;
    }

    return headers;
  }

  // Process request through interceptors
  async processRequest(url, options) {
    let processedUrl = url;
    let processedOptions = options;

    for (const interceptor of this.requestInterceptors) {
      const result = await interceptor(processedUrl, processedOptions);
      processedUrl = result.url || processedUrl;
      processedOptions = result.options || processedOptions;
    }

    return { url: processedUrl, options: processedOptions };
  }

  // Process response through interceptors
  async processResponse(response, url) {
    let processedResponse = response;

    for (const interceptor of this.responseInterceptors) {
      processedResponse = await interceptor(processedResponse, url);
    }

    return processedResponse;
  }

  // Phương thức yêu cầu chung
  async request(url, options = {}) {
    try {
      // Xử lý yêu cầu qua các bộ chặn
      const processed = await this.processRequest(url, options);

      // Xác định URL cơ sở chính xác (backend thật vs giả lập)
      let finalUrl = processed.url;
      if (processed.url.startsWith(API_CONFIG.BASE_URL)) {
        const baseUrl = await backendDetector.getBaseUrl();
        finalUrl = processed.url.replace(API_CONFIG.BASE_URL, baseUrl);
      }
      
      // Thực hiện yêu cầu
      const response = await fetch(finalUrl, {
        ...processed.options,
        headers: this.getHeaders(processed.options.headers)
      });

      // Xử lý phản hồi qua các bộ chặn
      const processedResponse = await this.processResponse(response, url);

      // Xử lý lỗi
      if (!processedResponse.ok) {
        const error = await processedResponse.json().catch(() => ({
          message: `HTTP ${processedResponse.status}: ${processedResponse.statusText}`
        }));
        throw new Error(error.message || error.detail || 'Yêu cầu thất bại');
      }

      // Phân tích phản hồi JSON
      const data = await processedResponse.json().catch(() => null);
      return data;

    } catch (error) {
      // Chỉ log nếu không phải lỗi từ chối kết nối (dự kiến khi API DensePose không chạy)
      if (error.message && !error.message.includes('Failed to fetch')) {
        console.error('Lỗi Yêu cầu API:', error);
      }
      throw error;
    }
  }

  // Yêu cầu GET
  async get(endpoint, params = {}, options = {}) {
    const url = buildApiUrl(endpoint, params);
    return this.request(url, {
      method: 'GET',
      ...options
    });
  }

  // Yêu cầu POST
  async post(endpoint, data = {}, options = {}) {
    const url = buildApiUrl(endpoint);
    return this.request(url, {
      method: 'POST',
      body: JSON.stringify(data),
      ...options
    });
  }

  // Yêu cầu PUT
  async put(endpoint, data = {}, options = {}) {
    const url = buildApiUrl(endpoint);
    return this.request(url, {
      method: 'PUT',
      body: JSON.stringify(data),
      ...options
    });
  }

  // Yêu cầu DELETE
  async delete(endpoint, options = {}) {
    const url = buildApiUrl(endpoint);
    return this.request(url, {
      method: 'DELETE',
      ...options
    });
  }
}

// Tạo thể hiện singleton
export const apiService = new ApiService();