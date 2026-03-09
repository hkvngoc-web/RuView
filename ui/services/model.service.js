// Dịch vụ Mô hình cho Giao diện WiFi-DensePose
// Quản lý tải mô hình, liệt kê, hồ sơ LoRA và sự kiện vòng đời.

import { apiService } from './api.service.js';

export class ModelService {
  constructor() {
    this.activeModel = null;
    this.listeners = {};
    this.logger = this.createLogger();
  }

  createLogger() {
    return {
      debug: (...args) => console.debug('[MODEL-DEBUG]', new Date().toISOString(), ...args),
      info: (...args) => console.info('[MODEL-INFO]', new Date().toISOString(), ...args),
      warn: (...args) => console.warn('[MODEL-WARN]', new Date().toISOString(), ...args),
      error: (...args) => console.error('[MODEL-ERROR]', new Date().toISOString(), ...args)
    };
  }

  // --- Trợ giúp bộ phát sự kiện ---

  on(event, callback) {
    if (!this.listeners[event]) {
      this.listeners[event] = [];
    }
    this.listeners[event].push(callback);
    return () => this.off(event, callback);
  }

  off(event, callback) {
    if (!this.listeners[event]) return;
    this.listeners[event] = this.listeners[event].filter(cb => cb !== callback);
  }

  emit(event, data) {
    if (!this.listeners[event]) return;
    this.listeners[event].forEach(cb => {
      try { cb(data); } catch (err) { this.logger.error('Lỗi trình nghe', { event, err }); }
    });
  }

  // --- Phương thức API ---

  async listModels() {
    try {
      const data = await apiService.get('/api/v1/models');
      this.logger.info('Đã liệt kê mô hình', { count: data?.models?.length ?? 0 });
      return data;
    } catch (error) {
      this.logger.error('Không thể liệt kê mô hình', { error: error.message });
      throw error;
    }
  }

  async getModel(id) {
    try {
      const data = await apiService.get(`/api/v1/models/${encodeURIComponent(id)}`);
      return data;
    } catch (error) {
      this.logger.error('Không thể lấy mô hình', { id, error: error.message });
      throw error;
    }
  }

  async loadModel(modelId) {
    try {
      this.logger.info('Đang tải mô hình', { modelId });
      const data = await apiService.post('/api/v1/models/load', { model_id: modelId });
      this.activeModel = { model_id: modelId };
      this.emit('model-loaded', { model_id: modelId });
      return data;
    } catch (error) {
      this.logger.error('Không thể tải mô hình', { modelId, error: error.message });
      throw error;
    }
  }

  async unloadModel() {
    try {
      this.logger.info('Đang gỡ mô hình');
      const data = await apiService.post('/api/v1/models/unload', {});
      this.activeModel = null;
      this.emit('model-unloaded', {});
      return data;
    } catch (error) {
      this.logger.error('Không thể gỡ mô hình', { error: error.message });
      throw error;
    }
  }

  async getActiveModel() {
    try {
      const data = await apiService.get('/api/v1/models/active');
      this.activeModel = data || null;
      return this.activeModel;
    } catch (error) {
      if (error.status === 404) {
        this.activeModel = null;
        return null;
      }
      this.logger.error('Không thể lấy mô hình đang hoạt động', { error: error.message });
      throw error;
    }
  }

  async activateLoraProfile(modelId, profileName) {
    try {
      this.logger.info('Đang kích hoạt hồ sơ LoRA', { modelId, profileName });
      const data = await apiService.post(
        '/api/v1/models/lora/activate',
        { model_id: modelId, profile_name: profileName }
      );
      this.emit('lora-activated', { model_id: modelId, profile: profileName });
      return data;
    } catch (error) {
      this.logger.error('Không thể kích hoạt LoRA', { modelId, profileName, error: error.message });
      throw error;
    }
  }

  async getLoraProfiles() {
    try {
      const data = await apiService.get('/api/v1/models/lora/profiles');
      return data?.profiles ?? [];
    } catch (error) {
      this.logger.error('Không thể lấy hồ sơ LoRA', { error: error.message });
      throw error;
    }
  }

  async deleteModel(id) {
    try {
      this.logger.info('Đang xoá mô hình', { id });
      const data = await apiService.delete(`/api/v1/models/${encodeURIComponent(id)}`);
      return data;
    } catch (error) {
      this.logger.error('Không thể xoá mô hình', { id, error: error.message });
      throw error;
    }
  }

  dispose() {
    this.listeners = {};
    this.activeModel = null;
    this.logger.info('Đã giải phóng ModelService');
  }
}

// Tạo thể hiện singleton
export const modelService = new ModelService();
