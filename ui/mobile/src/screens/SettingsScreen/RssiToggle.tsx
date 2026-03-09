import { Platform, Switch, View } from 'react-native';
import { ThemedText } from '@/components/ThemedText';
import { colors } from '@/theme/colors';
import { spacing } from '@/theme/spacing';

type RssiToggleProps = {
  enabled: boolean;
  onChange: (value: boolean) => void;
};

export const RssiToggle = ({ enabled, onChange }: RssiToggleProps) => {
  return (
    <View>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }}>
        <View style={{ flex: 1 }}>
          <ThemedText preset="bodyMd">Quét RSSI</ThemedText>
          <ThemedText preset="bodySm" style={{ color: colors.textSecondary }}>
            Quét tín hiệu Wi-Fi lân cận từ thiết bị Android
          </ThemedText>
        </View>
        <Switch
          value={enabled}
          onValueChange={onChange}
          trackColor={{ true: colors.accent, false: colors.surfaceAlt }}
          thumbColor={colors.textPrimary}
        />
      </View>

      {Platform.OS === 'ios' && (
        <ThemedText preset="bodySm" style={{ color: colors.textSecondary, marginTop: spacing.xs }}>
          iOS: Quét RSSI hiện bị giới hạn — sử dụng dữ liệu giả lập.
        </ThemedText>
      )}
    </View>
  );
};
