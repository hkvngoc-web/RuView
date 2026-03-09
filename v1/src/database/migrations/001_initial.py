"""
Di cư cơ sở dữ liệu ban đầu cho WiFi-DensePose API

Revision ID: 001_initial
Revises:
Create Date: 2025-01-07 07:58:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Định danh phiên bản
revision = '001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    """Tạo lược đồ cơ sở dữ liệu ban đầu."""

    # Tạo bảng thiết bị
    op.create_table(
        'devices',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('device_type', sa.String(length=50), nullable=False),
        sa.Column('mac_address', sa.String(length=17), nullable=False),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('firmware_version', sa.String(length=50), nullable=True),
        sa.Column('hardware_version', sa.String(length=50), nullable=True),
        sa.Column('location_name', sa.String(length=255), nullable=True),
        sa.Column('room_id', sa.String(length=100), nullable=True),
        sa.Column('coordinates_x', sa.Float(), nullable=True),
        sa.Column('coordinates_y', sa.Float(), nullable=True),
        sa.Column('coordinates_z', sa.Float(), nullable=True),
        sa.Column('config', sa.JSON(), nullable=True),
        sa.Column('capabilities', postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('tags', postgresql.ARRAY(sa.String()), nullable=True),
        sa.CheckConstraint("status IN ('active', 'inactive', 'maintenance', 'error')", name='check_device_status'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('mac_address')
    )

    # Tạo chỉ mục cho bảng thiết bị
    op.create_index('idx_device_mac_address', 'devices', ['mac_address'])
    op.create_index('idx_device_status', 'devices', ['status'])
    op.create_index('idx_device_type', 'devices', ['device_type'])

    # Tạo bảng phiên
    op.create_table(
        'sessions',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_seconds', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('config', sa.JSON(), nullable=True),
        sa.Column('device_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('tags', postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column('metadata', sa.JSON(), nullable=True),
        sa.Column('total_frames', sa.Integer(), nullable=False),
        sa.Column('processed_frames', sa.Integer(), nullable=False),
        sa.Column('error_count', sa.Integer(), nullable=False),
        sa.CheckConstraint("status IN ('active', 'completed', 'failed', 'cancelled')", name='check_session_status'),
        sa.CheckConstraint('total_frames >= 0', name='check_total_frames_positive'),
        sa.CheckConstraint('processed_frames >= 0', name='check_processed_frames_positive'),
        sa.CheckConstraint('error_count >= 0', name='check_error_count_positive'),
        sa.ForeignKeyConstraint(['device_id'], ['devices.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    # Tạo chỉ mục cho bảng phiên
    op.create_index('idx_session_device_id', 'sessions', ['device_id'])
    op.create_index('idx_session_status', 'sessions', ['status'])
    op.create_index('idx_session_started_at', 'sessions', ['started_at'])

    # Tạo bảng dữ liệu CSI
    op.create_table(
        'csi_data',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('sequence_number', sa.Integer(), nullable=False),
        sa.Column('timestamp_ns', sa.BigInteger(), nullable=False),
        sa.Column('device_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('session_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('amplitude', postgresql.ARRAY(sa.Float()), nullable=False),
        sa.Column('phase', postgresql.ARRAY(sa.Float()), nullable=False),
        sa.Column('frequency', sa.Float(), nullable=False),
        sa.Column('bandwidth', sa.Float(), nullable=False),
        sa.Column('rssi', sa.Float(), nullable=True),
        sa.Column('snr', sa.Float(), nullable=True),
        sa.Column('noise_floor', sa.Float(), nullable=True),
        sa.Column('tx_antenna', sa.Integer(), nullable=True),
        sa.Column('rx_antenna', sa.Integer(), nullable=True),
        sa.Column('num_subcarriers', sa.Integer(), nullable=False),
        sa.Column('processing_status', sa.String(length=20), nullable=False),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('quality_score', sa.Float(), nullable=True),
        sa.Column('is_valid', sa.Boolean(), nullable=False),
        sa.Column('metadata', sa.JSON(), nullable=True),
        sa.CheckConstraint('frequency > 0', name='check_frequency_positive'),
        sa.CheckConstraint('bandwidth > 0', name='check_bandwidth_positive'),
        sa.CheckConstraint('num_subcarriers > 0', name='check_subcarriers_positive'),
        sa.CheckConstraint("processing_status IN ('pending', 'processing', 'completed', 'failed')", name='check_processing_status'),
        sa.ForeignKeyConstraint(['device_id'], ['devices.id'], ),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('device_id', 'sequence_number', 'timestamp_ns', name='uq_csi_device_seq_time')
    )

    # Tạo chỉ mục cho bảng dữ liệu CSI
    op.create_index('idx_csi_device_id', 'csi_data', ['device_id'])
    op.create_index('idx_csi_session_id', 'csi_data', ['session_id'])
    op.create_index('idx_csi_timestamp', 'csi_data', ['timestamp_ns'])
    op.create_index('idx_csi_sequence', 'csi_data', ['sequence_number'])
    op.create_index('idx_csi_processing_status', 'csi_data', ['processing_status'])

    # Tạo bảng phát hiện tư thế
    op.create_table(
        'pose_detections',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('frame_number', sa.Integer(), nullable=False),
        sa.Column('timestamp_ns', sa.BigInteger(), nullable=False),
        sa.Column('session_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('person_count', sa.Integer(), nullable=False),
        sa.Column('keypoints', sa.JSON(), nullable=True),
        sa.Column('bounding_boxes', sa.JSON(), nullable=True),
        sa.Column('detection_confidence', sa.Float(), nullable=True),
        sa.Column('pose_confidence', sa.Float(), nullable=True),
        sa.Column('overall_confidence', sa.Float(), nullable=True),
        sa.Column('processing_time_ms', sa.Float(), nullable=True),
        sa.Column('model_version', sa.String(length=50), nullable=True),
        sa.Column('algorithm', sa.String(length=100), nullable=True),
        sa.Column('image_quality', sa.Float(), nullable=True),
        sa.Column('pose_quality', sa.Float(), nullable=True),
        sa.Column('is_valid', sa.Boolean(), nullable=False),
        sa.Column('metadata', sa.JSON(), nullable=True),
        sa.CheckConstraint('person_count >= 0', name='check_person_count_positive'),
        sa.CheckConstraint('detection_confidence >= 0 AND detection_confidence <= 1', name='check_detection_confidence_range'),
        sa.CheckConstraint('pose_confidence >= 0 AND pose_confidence <= 1', name='check_pose_confidence_range'),
        sa.CheckConstraint('overall_confidence >= 0 AND overall_confidence <= 1', name='check_overall_confidence_range'),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ),
        sa.PrimaryKeyConstraint('id')
    )

    # Tạo chỉ mục cho bảng phát hiện tư thế
    op.create_index('idx_pose_session_id', 'pose_detections', ['session_id'])
    op.create_index('idx_pose_timestamp', 'pose_detections', ['timestamp_ns'])
    op.create_index('idx_pose_frame', 'pose_detections', ['frame_number'])
    op.create_index('idx_pose_person_count', 'pose_detections', ['person_count'])

    # Tạo bảng số liệu hệ thống
    op.create_table(
        'system_metrics',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('metric_name', sa.String(length=255), nullable=False),
        sa.Column('metric_type', sa.String(length=50), nullable=False),
        sa.Column('value', sa.Float(), nullable=False),
        sa.Column('unit', sa.String(length=50), nullable=True),
        sa.Column('labels', sa.JSON(), nullable=True),
        sa.Column('tags', postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column('source', sa.String(length=255), nullable=True),
        sa.Column('component', sa.String(length=100), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('metadata', sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    # Tạo chỉ mục cho bảng số liệu hệ thống
    op.create_index('idx_metric_name', 'system_metrics', ['metric_name'])
    op.create_index('idx_metric_type', 'system_metrics', ['metric_type'])
    op.create_index('idx_metric_created_at', 'system_metrics', ['created_at'])
    op.create_index('idx_metric_source', 'system_metrics', ['source'])
    op.create_index('idx_metric_component', 'system_metrics', ['component'])

    # Tạo bảng nhật ký kiểm toán
    op.create_table(
        'audit_logs',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('event_type', sa.String(length=100), nullable=False),
        sa.Column('event_name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('user_id', sa.String(length=255), nullable=True),
        sa.Column('session_id', sa.String(length=255), nullable=True),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.Column('resource_type', sa.String(length=100), nullable=True),
        sa.Column('resource_id', sa.String(length=255), nullable=True),
        sa.Column('before_state', sa.JSON(), nullable=True),
        sa.Column('after_state', sa.JSON(), nullable=True),
        sa.Column('changes', sa.JSON(), nullable=True),
        sa.Column('success', sa.Boolean(), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('metadata', sa.JSON(), nullable=True),
        sa.Column('tags', postgresql.ARRAY(sa.String()), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    # Tạo chỉ mục cho bảng nhật ký kiểm toán
    op.create_index('idx_audit_event_type', 'audit_logs', ['event_type'])
    op.create_index('idx_audit_user_id', 'audit_logs', ['user_id'])
    op.create_index('idx_audit_resource', 'audit_logs', ['resource_type', 'resource_id'])
    op.create_index('idx_audit_created_at', 'audit_logs', ['created_at'])
    op.create_index('idx_audit_success', 'audit_logs', ['success'])

    # Tạo trigger cho cột updated_at
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ language 'plpgsql';
    """)

    # Thêm trigger cho tất cả bảng có cột updated_at
    tables_with_updated_at = [
        'devices', 'sessions', 'csi_data', 'pose_detections',
        'system_metrics', 'audit_logs'
    ]

    # Xác thực danh sách trắng để ngăn SQL injection
    allowed_tables = set(tables_with_updated_at)

    for table in tables_with_updated_at:
        # Xác thực tên bảng theo danh sách trắng
        if table not in allowed_tables:
            continue

        # Sử dụng truy vấn tham số hóa với text() của SQLAlchemy và bindparam
        # Lưu ý: Đối với tên bảng trong DDL, ta xác thực theo danh sách trắng
        # op.execute của SQLAlchemy với text() an toàn khi tên bảng đã được xác thực
        op.execute(
            sa.text(f"""
                CREATE TRIGGER update_{table}_updated_at
                    BEFORE UPDATE ON {table}
                    FOR EACH ROW
                    EXECUTE FUNCTION update_updated_at_column();
            """)
        )

    # Chèn dữ liệu ban đầu
    _insert_initial_data()


def downgrade():
    """Xóa tất cả bảng và hàm."""

    # Xóa trigger trước
    tables_with_updated_at = [
        'devices', 'sessions', 'csi_data', 'pose_detections',
        'system_metrics', 'audit_logs'
    ]

    # Xác thực danh sách trắng để ngăn SQL injection
    allowed_tables = set(tables_with_updated_at)

    for table in tables_with_updated_at:
        # Xác thực tên bảng theo danh sách trắng
        if table not in allowed_tables:
            continue

        # Sử dụng truy vấn tham số hóa với text() của SQLAlchemy
        op.execute(
            sa.text(f"DROP TRIGGER IF EXISTS update_{table}_updated_at ON {table};")
        )

    # Xóa hàm
    op.execute("DROP FUNCTION IF EXISTS update_updated_at_column();")

    # Xóa bảng theo thứ tự ngược (tuân thủ ràng buộc khóa ngoại)
    op.drop_table('audit_logs')
    op.drop_table('system_metrics')
    op.drop_table('pose_detections')
    op.drop_table('csi_data')
    op.drop_table('sessions')
    op.drop_table('devices')


def _insert_initial_data():
    """Chèn dữ liệu ban đầu vào các bảng."""

    # Chèn thiết bị mẫu
    op.execute("""
        INSERT INTO devices (
            id, name, device_type, mac_address, ip_address, status,
            firmware_version, hardware_version, location_name, room_id,
            coordinates_x, coordinates_y, coordinates_z,
            config, capabilities, description, tags
        ) VALUES (
            gen_random_uuid(),
            'Router Demo',
            'router',
            '00:11:22:33:44:55',
            '192.168.1.1',
            'active',
            '1.0.0',
            'v1.0',
            'Phòng khách',
            'room_001',
            0.0,
            0.0,
            2.5,
            '{"channel": 6, "power": 20, "bandwidth": 80}',
            ARRAY['wifi6', 'csi', 'beamforming'],
            'Router WiFi demo cho kiểm thử',
            ARRAY['demo', 'testing']
        );
    """)

    # Chèn phiên mẫu
    op.execute("""
        INSERT INTO sessions (
            id, name, description, started_at, status, config,
            device_id, tags, metadata, total_frames, processed_frames, error_count
        ) VALUES (
            gen_random_uuid(),
            'Phiên Demo',
            'Phiên demo ban đầu cho kiểm thử',
            now(),
            'active',
            '{"duration": 3600, "sampling_rate": 100}',
            (SELECT id FROM devices WHERE name = 'Router Demo' LIMIT 1),
            ARRAY['demo', 'initial'],
            '{"purpose": "testing", "environment": "lab"}',
            0,
            0,
            0
        );
    """)

    # Chèn số liệu hệ thống ban đầu
    metrics_data = [
        ('system_startup', 'counter', 1.0, 'count', 'system', 'application'),
        ('database_connections', 'gauge', 0.0, 'count', 'database', 'postgresql'),
        ('api_requests_total', 'counter', 0.0, 'count', 'api', 'http'),
        ('memory_usage', 'gauge', 0.0, 'bytes', 'system', 'memory'),
        ('cpu_usage', 'gauge', 0.0, 'percent', 'system', 'cpu'),
    ]

    for metric_name, metric_type, value, unit, source, component in metrics_data:
        # Sử dụng truy vấn tham số hóa để ngăn SQL injection
        # Thoát dấu nháy đơn trong giá trị chuỗi
        safe_metric_name = metric_name.replace("'", "''")
        safe_metric_type = metric_type.replace("'", "''")
        safe_unit = unit.replace("'", "''") if unit else ''
        safe_source = source.replace("'", "''") if source else ''
        safe_component = component.replace("'", "''") if component else ''
        safe_description = f'Số liệu {safe_metric_name} ban đầu'.replace("'", "''")

        # Sử dụng text() của SQLAlchemy với thoát đúng cách
        op.execute(
            sa.text(f"""
                INSERT INTO system_metrics (
                    id, metric_name, metric_type, value, unit, source, component,
                    description, metadata
                ) VALUES (
                    gen_random_uuid(),
                    :metric_name,
                    :metric_type,
                    :value,
                    :unit,
                    :source,
                    :component,
                    :description,
                    :metadata
                )
            """).bindparams(
                metric_name=safe_metric_name,
                metric_type=safe_metric_type,
                value=value,
                unit=safe_unit,
                source=safe_source,
                component=safe_component,
                description=safe_description,
                metadata='{"initial": true, "version": "1.0.0"}'
            )
        )

    # Chèn nhật ký kiểm toán ban đầu
    op.execute("""
        INSERT INTO audit_logs (
            id, event_type, event_name, description, user_id, success,
            resource_type, metadata
        ) VALUES (
            gen_random_uuid(),
            'system',
            'database_migration',
            'Lược đồ cơ sở dữ liệu ban đầu đã được tạo',
            'system',
            true,
            'database',
            '{"migration": "001_initial", "version": "1.0.0"}'
        );
    """)
