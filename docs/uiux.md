

# UI/UX 設計・実装ルール（React Native/Expo）

## 1. デザインシステム

### 重要度: 最高

- NativeWind（Tailwind CSS for RN）をベースとしたスタイリング

-**既存の UI は承認なしでの変更を禁止**

- コンポーネントのカスタマイズは最小限に抑える

```typescript

// ✅ 良い例：NativeWindを使用

import { View, Text } from"react-native";


<View className="flex-1 items-center justify-center p-4">

  <Text className="text-lg font-bold">Hello</Text>

</View>


// ❌ 悪い例：インラインスタイル

<View style={{ flex: 1, alignItems: 'center', justifyContent: 'center' }}>

  <Text style={{ fontSize: 18, fontWeight: 'bold' }}>Hello</Text>

</View>

```

## 2. スタイリング規約

### 重要度: 高

### NativeWind の使用

- ユーティリティクラスを優先的に使用
- StyleSheet は特殊なケースのみ使用
- 命名規則は `kebab-case`を使用

```typescript

// ✅ 良い例：NativeWind

<View className="flex-row items-center gap-2 p-4 bg-white rounded-lg">

  <Text className="text-base text-gray-800">タイトル</Text>

</View>


// ⚠️ 許容：動的スタイルが必要な場合のみStyleSheet

import { StyleSheet } from"react-native";


const styles = StyleSheet.create({

  dynamicHeight: {

    height: calculatedHeight,

  },

});

```

### 色の定義

```typescript

// tailwind.config.js で色を定義

module.exports= {

  theme: {

    extend: {

      colors: {

        primary: "#007AFF",

        secondary: "#5856D6",

        success: "#34C759",

        warning: "#FF9500",

        error: "#FF3B30",

      },

    },

  },

};

```

## 3. プラットフォーム対応

### 重要度: 高

- iOS / Android 両方で一貫した体験を提供
- プラットフォーム固有の調整は最小限に

```typescript

import { Platform } from"react-native";


// ✅ 良い例：NativeWindのプラットフォーム対応

<View className="ios:pt-12 android:pt-4">


// プラットフォーム固有の処理が必要な場合

{Platform.OS ==="ios"? (

  <IOSComponent />

) : (

  <AndroidComponent />

)}

```

## 4. アクセシビリティ

### 重要度: 高

- accessibilityLabel を適切に設定
- accessibilityRole を正しく指定
- accessibilityHint でヒントを提供

```typescript

// ✅ 良い例

<TouchableOpacity

  accessibilityLabel="プロフィールを編集"

  accessibilityRole="button"

  accessibilityHint="プロフィール編集画面に移動します"

  onPress={handleEdit}

>

  <Text>編集</Text>

</TouchableOpacity>


// 画像のアクセシビリティ

<Image

  source={{ uri: imageUrl }}

  accessibilityLabel="ユーザーのプロフィール画像"

/>

```

## 5. アニメーションとトランジション

### 重要度: 中

- React Native Reanimated を使用
- 過度なアニメーションを避ける
- 60fps を維持できるアニメーションのみ実装

```typescript

import Animated, {

  useSharedValue,

  useAnimatedStyle,

  withSpring,

} from"react-native-reanimated";


// ✅ 良い例

const opacity =useSharedValue(0);


const animatedStyle =useAnimatedStyle(() => ({

  opacity: opacity.value,

}));


// アニメーション実行

opacity.value =withSpring(1);


<Animated.View style={animatedStyle}>

  <Text>コンテンツ</Text>

</Animated.View>

```

## 6. フォーム設計

### 重要度: 高

- React Hook Form + Zod でバリデーション
- エラーメッセージは明確に表示
- キーボード対応を適切に実装

```typescript

import { KeyboardAvoidingView, Platform, ScrollView } from"react-native";


// ✅ 良い例：キーボード対応

<KeyboardAvoidingView

  behavior={Platform.OS ==="ios"?"padding":"height"}

  className="flex-1"

>

  <ScrollView keyboardShouldPersistTaps="handled">

    {/* フォーム内容 */}

  </ScrollView>

</KeyboardAvoidingView>

```

## 7. 重要な制約事項

### 重要度: 最高

1. UI 変更の制限

-**既存の UI コンポーネントやレイアウトの変更は禁止**

-**変更が必要な場合は必ず事前承認を得ること**

- レイアウト、色、フォント、間隔などの変更は特に注意

2. コンポーネントの追加

- 新規コンポーネントは既存の設計原則に従う
- 既存のコンポーネントの再利用を優先

## 8. フィードバックとローディング

### 重要度: 高

### ローディング状態

```typescript

import { View, ActivityIndicator } from"react-native";


// ✅ 良い例

{isLoading ? (

  <View className="flex-1 items-center justify-center">

    <ActivityIndicator size="large" color="#007AFF"/>

  </View>

) : (

  <Content />

)}

```

### 触覚フィードバック

```typescript

import*as Haptics from"expo-haptics";


// ボタン押下時

consthandlePress=async () => {

  await Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);

  // 処理

};


// 成功時

await Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);


// エラー時

await Haptics.notificationAsync(Haptics.NotificationFeedbackType.Error);

```

### トースト通知

```typescript

import Toast from"react-native-toast-message";


// 成功

Toast.show({

  type: "success",

  text1: "保存しました",

});


// エラー

Toast.show({

  type: "error",

  text1: "エラー",

  text2: "保存に失敗しました",

});

```

## 9. アイコンと画像

### 重要度: 中

### アイコン

```typescript

// ✅ 良い例：lucide-react-native

import { Home, User, Settings } from"lucide-react-native";


<Home size={24} color="#007AFF"/>

```

### 画像最適化

```typescript

// ✅ 良い例：expo-image

import { Image } from"expo-image";


<Image

  source={{ uri: imageUrl }}

  style={{ width: 100, height: 100 }}

  contentFit="cover"

  placeholder={blurhash}

  transition={200}

/>

```

## 10. ダークモード対応

### 重要度: 高

```typescript

import { useColorScheme, View, Text } from"react-native";


// NativeWindでのダークモード

<View className="bg-white dark:bg-gray-900">

  <Text className="text-gray-900 dark:text-white">

    テキスト

  </Text>

</View>


// プログラマティックに取得

const colorScheme =useColorScheme();

const isDark = colorScheme ==="dark";

```

## 11. コンポーネント設計原則

### 重要度: 高

- 単一責任の原則
- Props 経由での柔軟なカスタマイズ
- 適切なコンポーネント分割

```typescript

// ✅ 良い例

interfaceCardProps {

  title:string;

  children:React.ReactNode;

  className?:string;

  onPress?: () =>void;

}


exportfunctionCard({ title, children, className, onPress }:CardProps) {

  return (

    <TouchableOpacity

      onPress={onPress}

      disabled={!onPress}

      className={cn("bg-white rounded-lg p-4 shadow-sm", className)}

    >

      <Text className="text-lg font-bold mb-2">{title}</Text>

      {children}

    </TouchableOpacity>

  );

}


// ❌ 悪い例

interfaceCardProps {

  title:string;

  titleColor:string; // 不要なカスタマイズ

  customPadding:number; // 避けるべき

}

```

## 12. セーフエリア対応

### 重要度: 高

```typescript

import { SafeAreaView } from"react-native-safe-area-context";


// ✅ 良い例

<SafeAreaView className="flex-1 bg-white">

  <Content />

</SafeAreaView>


// 特定のエッジのみ

<SafeAreaView edges={["top"]} className="flex-1">

  <Content />

</SafeAreaView>

```

## 13. スクロールとリスト

### 重要度: 高

```typescript

// 通常のスクロール

import { ScrollView } from"react-native";


<ScrollView

  className="flex-1"

  showsVerticalScrollIndicator={false}

  contentContainerStyle={{ paddingBottom: 20 }}

>

  {/* コンテンツ */}

</ScrollView>


// 大量データ

import { FlashList } from"@shopify/flash-list";


<FlashList

  data={items}

  renderItem={({ item }) => <ItemCard item={item} />}

  estimatedItemSize={80}

/>

```

## 注意事項

1. デザインの一貫性

- NativeWind クラスの一貫した使用
- カスタムスタイルの最小化
- デザイントークンの遵守

2. パフォーマンス

- 不要な再レンダリングの防止（memo, useMemo, useCallback）
- 画像の最適化（expo-image）
- リストの最適化（FlashList）

3. テスト

- コンポーネントのスナップショットテスト
- 複数デバイスでの表示確認
- iOS / Android 両方でテスト

4. ドキュメント

- コンポーネントの使用例
- Props の型定義
- デザインシステムのガイドライン

これらのルールは、プロジェクトの一貫性と保守性を確保するために重要です。

変更が必要な場合は、必ずチームでの承認プロセスを経てください。
