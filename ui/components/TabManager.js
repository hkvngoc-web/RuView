// Thành phần Quản lý Tab

export class TabManager {
  constructor(containerElement) {
    this.container = containerElement;
    this.tabs = [];
    this.activeTab = null;
    this.tabChangeCallbacks = [];
  }

  // Khởi tạo các tab
  init() {
    // Tìm tất cả tab và nội dung
    this.tabs = Array.from(this.container.querySelectorAll('.nav-tab'));
    this.tabContents = Array.from(this.container.querySelectorAll('.tab-content'));
    
    // Thiết lập bộ lắng nghe sự kiện
    this.tabs.forEach(tab => {
      tab.addEventListener('click', () => this.switchTab(tab));
    });

    // Kích hoạt tab đầu tiên nếu chưa có tab nào hoạt động
    const activeTab = this.tabs.find(tab => tab.classList.contains('active'));
    if (activeTab) {
      this.activeTab = activeTab.getAttribute('data-tab');
    } else if (this.tabs.length > 0) {
      this.switchTab(this.tabs[0]);
    }
  }

  // Chuyển sang tab
  switchTab(tabElement) {
    const tabId = tabElement.getAttribute('data-tab');
    
    if (tabId === this.activeTab) {
      return;
    }

    // Cập nhật trạng thái tab
    this.tabs.forEach(tab => {
      tab.classList.toggle('active', tab === tabElement);
    });

    // Cập nhật hiển thị nội dung
    this.tabContents.forEach(content => {
      content.classList.toggle('active', content.id === tabId);
    });

    // Cập nhật tab đang hoạt động
    const previousTab = this.activeTab;
    this.activeTab = tabId;

    // Thông báo callback
    this.notifyTabChange(tabId, previousTab);
  }

  // Chuyển sang tab theo ID
  switchToTab(tabId) {
    const tab = this.tabs.find(t => t.getAttribute('data-tab') === tabId);
    if (tab) {
      this.switchTab(tab);
    }
  }

  // Đăng ký callback thay đổi tab
  onTabChange(callback) {
    this.tabChangeCallbacks.push(callback);
    
    // Trả về hàm huỷ đăng ký
    return () => {
      const index = this.tabChangeCallbacks.indexOf(callback);
      if (index > -1) {
        this.tabChangeCallbacks.splice(index, 1);
      }
    };
  }

  // Thông báo các callback thay đổi tab
  notifyTabChange(newTab, previousTab) {
    this.tabChangeCallbacks.forEach(callback => {
      try {
        callback(newTab, previousTab);
      } catch (error) {
        console.error('Lỗi trong callback thay đổi tab:', error);
      }
    });
  }

  // Lấy tab đang hoạt động
  getActiveTab() {
    return this.activeTab;
  }

  // Bật/tắt tab
  setTabEnabled(tabId, enabled) {
    const tab = this.tabs.find(t => t.getAttribute('data-tab') === tabId);
    if (tab) {
      tab.disabled = !enabled;
      tab.classList.toggle('disabled', !enabled);
    }
  }

  // Hiện/ẩn tab
  setTabVisible(tabId, visible) {
    const tab = this.tabs.find(t => t.getAttribute('data-tab') === tabId);
    if (tab) {
      tab.style.display = visible ? '' : 'none';
    }
  }

  // Thêm huy hiệu vào tab
  setTabBadge(tabId, badge) {
    const tab = this.tabs.find(t => t.getAttribute('data-tab') === tabId);
    if (!tab) return;

    // Xoá huy hiệu hiện tại
    const existingBadge = tab.querySelector('.tab-badge');
    if (existingBadge) {
      existingBadge.remove();
    }

    // Thêm huy hiệu mới nếu có
    if (badge) {
      const badgeElement = document.createElement('span');
      badgeElement.className = 'tab-badge';
      badgeElement.textContent = badge;
      tab.appendChild(badgeElement);
    }
  }

  // Dọn dẹp
  dispose() {
    this.tabs.forEach(tab => {
      tab.removeEventListener('click', this.switchTab);
    });
    this.tabChangeCallbacks = [];
  }
}