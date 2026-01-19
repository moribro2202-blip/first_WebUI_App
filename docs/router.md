

# Expo Router ベストプラクティス実装ルール

## 1. ルーティングとファイル構造

### ディレクトリ構造例

src/

├── app/                    # Expo Router ページ

│   ├── (tabs)/            # タブナビゲーション

│   │   ├── index.tsx      # ホームタブ

│   │   ├── search.tsx     # 検索タブ

│   │   ├── favorites.tsx  # お気に入りタブ

│   │   ├── profile.tsx    # プロフィールタブ

│   │   └── _layout.tsx    # タブレイアウト

│   ├── (auth)/            # 認証画面（タブ非表示）

│   │   ├── sign-in.tsx

│   │   ├── sign-up.tsx

│   │   └── _layout.tsx

│   ├── (modals)/          # モーダル画面

│   │   ├── settings.tsx

│   │   └── _layout.tsx

│   ├── [id]/              # 動的ルート

│   │   └── index.tsx

│   ├── _layout.tsx        # ルートレイアウト

│   └── +not-found.tsx     # 404ページ

│

├── components/            # Reactコンポーネント

│   ├── ui/               # 基本UIコンポーネント

│   │   ├── Button.tsx

│   │   ├── Card.tsx

│   │   ├── Input.tsx

│   │   └── Text.tsx

│   ├── features/         # 機能別コンポーネント

│   │   ├── auth/

│   │   ├── home/

│   │   └── profile/

│   └── layouts/          # レイアウトコンポーネント

│       ├── Header.tsx

│       └── TabBar.tsx

│

├── hooks/                # カスタムフック

│   ├── useAuth.ts

│   ├── useFirestore.ts

│   └── useStorage.ts

│

├── contexts/             # React Context

│   └── AuthContext.tsx

│

├── stores/               # Zustand ストア

│   ├── useUserStore.ts

│   └── useAppStore.ts

│

├── lib/                  # ユーティリティ関数

│   ├── firebase.ts      # Firebase設定

│   ├── constants.ts     # 定数

│   └── utils.ts         # ヘルパー関数

│

├── types/                # 型定義

│   ├── user.ts

│   └── api.ts

│

└── assets/               # 静的アセット

    ├── images/

    ├── fonts/

    └── icons/

### 命名規則

- ページコンポーネント: `index.tsx` または `[name].tsx`
- レイアウトコンポーネント: `_layout.tsx`
- 404ページ: `+not-found.tsx`
- 動的ルート: `[param].tsx` または `[...param].tsx`

## 2. ナビゲーション設計

### ルートレイアウト

```typescript

// app/_layout.tsx

import { Stack } from"expo-router";

import { AuthProvider } from"@/contexts/AuthContext";


exportdefaultfunctionRootLayout() {

  return (

    <AuthProvider>

      <Stack>

        <Stack.Screen name="(tabs)" options={{ headerShown: false }} />

        <Stack.Screen name="(auth)" options={{ headerShown: false }} />

        <Stack.Screen

          name="(modals)"

          options={{ presentation: "modal" }}

        />

      </Stack>

    </AuthProvider>

  );

}

```

### タブナビゲーション

```typescript

// app/(tabs)/_layout.tsx

import { Tabs } from"expo-router";

import { Home, Search, Heart, User } from"lucide-react-native";


exportdefaultfunctionTabLayout() {

  return (

    <Tabs

      screenOptions={{

        tabBarActiveTintColor: "#007AFF",

        headerShown: false,

      }}

    >

      <Tabs.Screen

        name="index"

        options={{

          title: "ホーム",

          tabBarIcon: ({ color }) => <Homesize={24} color={color} />,

        }}

      />

      <Tabs.Screen

        name="search"

        options={{

          title: "検索",

          tabBarIcon: ({ color }) => <Searchsize={24} color={color} />,

        }}

      />

      <Tabs.Screen

        name="favorites"

        options={{

          title: "お気に入り",

          tabBarIcon: ({ color }) => <Heartsize={24} color={color} />,

        }}

      />

      <Tabs.Screen

        name="profile"

        options={{

          title: "プロフィール",

          tabBarIcon: ({ color }) => <Usersize={24} color={color} />,

        }}

      />

    </Tabs>

  );

}

```

## 3. データフェッチング

### TanStack Query を使用

```typescript

// hooks/useItems.ts

import { useQuery, useMutation, useQueryClient } from"@tanstack/react-query";

import { collection, getDocs, addDoc } from"firebase/firestore";

import { db } from"@/lib/firebase";


exportfunctionuseItems() {

  returnuseQuery({

    queryKey: ["items"],

    queryFn: async () => {

      const snapshot =awaitgetDocs(collection(db, "items"));

      return snapshot.docs.map((doc) => ({

        id: doc.id,

        ...doc.data(),

      }));

    },

  });

}


exportfunctionuseCreateItem() {

  const queryClient =useQueryClient();


  returnuseMutation({

    mutationFn: async (data:ItemData) => {

      const docRef =awaitaddDoc(collection(db, "items"), data);

      return { id: docRef.id, ...data };

    },

    onSuccess: () => {

      queryClient.invalidateQueries({ queryKey: ["items"] });

    },

  });

}

```

### コンポーネントでの使用

```typescript

// app/(tabs)/index.tsx

import { View, FlatList, ActivityIndicator, Text } from"react-native";

import { useItems } from"@/hooks/useItems";

import { ItemCard } from"@/components/features/home/ItemCard";


exportdefaultfunctionHomeScreen() {

  const { data: items, isLoading, error } =useItems();


  if (isLoading) {

    return (

      <View className="flex-1 items-center justify-center">

        <ActivityIndicator size="large"/>

      </View>

    );

  }


  if (error) {

    return (

      <View className="flex-1 items-center justify-center">

        <Text>エラーが発生しました</Text>

      </View>

    );

  }


  return (

    <FlatList

      data={items}

      renderItem={({ item }) => <ItemCard item={item} />}

      keyExtractor={(item) => item.id}

    />

  );

}

```

## 4. ナビゲーション操作

### プログラマティックナビゲーション

```typescript

import { router } from"expo-router";


// 画面遷移

router.push("/profile");

router.push("/items/123");


// 置き換え（戻るボタンで戻れない）

router.replace("/(tabs)");


// 戻る

router.back();


// パラメータ付き遷移

router.push({

  pathname: "/items/[id]",

  params: { id: "123" },

});

```

### Link コンポーネント

```typescript

import { Link } from"expo-router";

import { Text } from"react-native";


<Link href="/profile">

  <Text>プロフィールへ</Text>

</Link>


<Link href={{ pathname: "/items/[id]", params: { id: "123" } }}>

  <Text>詳細を見る</Text>

</Link>

```

## 5. 認証ガード

### 認証が必要な画面の保護

```typescript

// app/(tabs)/_layout.tsx

import { Redirect } from"expo-router";

import { Tabs } from"expo-router";

import { useAuth } from"@/contexts/AuthContext";

import { LoadingScreen } from"@/components/ui/LoadingScreen";


exportdefaultfunctionTabLayout() {

  const { user, isLoading } =useAuth();


  if (isLoading) {

    return <LoadingScreen />;

  }


  if (!user) {

    return <Redirecthref="/(auth)/sign-in" />;

  }


  return (

    <Tabs>

      {/* タブ設定 */}

    </Tabs>

  );

}

```

## 6. パフォーマンス最適化

### 画像最適化

```typescript

import { Image } from"expo-image";


<Image

  source={{ uri: imageUrl }}

  style={{ width: 200, height: 200 }}

  contentFit="cover"

  placeholder={blurhash}

  transition={200}

/>

```

### リスト最適化

```typescript

import { FlashList } from"@shopify/flash-list";


<FlashList

  data={items}

  renderItem={({ item }) => <ItemCard item={item} />}

  estimatedItemSize={100}

  keyExtractor={(item) => item.id}

/>

```

### メモ化

```typescript

import { memo, useMemo, useCallback } from"react";


const ItemCard =memo(({ item }: { item:Item }) => {

  // コンポーネント内容

});

```

## 7. エラーハンドリング

### エラーバウンダリ

```typescript

// app/_layout.tsx

import { View, Text } from"react-native";

import { ErrorBoundaryProps } from"expo-router";

import { Button } from"@/components/ui/Button";


exportfunctionErrorBoundary({ error, retry }:ErrorBoundaryProps) {

  return (

    <View className="flex-1 items-center justify-center p-4">

      <Text className="text-lg font-bold mb-2">エラーが発生しました</Text>

      <Text className="text-gray-500 mb-4">{error.message}</Text>

      <Button onPress={retry}>再試行</Button>

    </View>

  );

}

```

### 404ページ

```typescript

// app/+not-found.tsx

import { View, Text } from"react-native";

import { Link } from"expo-router";


exportdefaultfunctionNotFoundScreen() {

  return (

    <View className="flex-1 items-center justify-center">

      <Text className="text-xl font-bold mb-4">

        ページが見つかりません

      </Text>

      <Link href="/">

        <Text className="text-blue-500">ホームに戻る</Text>

      </Link>

    </View>

  );

}

```

## 8. 型安全性

### TypeScript 設定

```json

{

  "compilerOptions": {

    "strict": true,

    "baseUrl": ".",

    "paths": {

      "@/*": ["src/*"]

    }

  }

}

```

### ルートパラメータの型定義

```typescript

// app/items/[id].tsx

import { useLocalSearchParams } from"expo-router";


typeParams= {

  id:string;

};


exportdefaultfunctionItemDetailScreen() {

  const { id } =useLocalSearchParams<Params>();

  // ...

}

```

## 9. 環境変数

### 設定

```env

EXPO_PUBLIC_FIREBASE_API_KEY=xxx

EXPO_PUBLIC_FIREBASE_PROJECT_ID=xxx

```

### 使用

```typescript

const apiKey = process.env.EXPO_PUBLIC_FIREBASE_API_KEY;

```

## 10. メンテナンス

### 依存関係

- 定期的に依存パッケージを更新

-`expo doctor` でプロジェクトの健全性を確認

### パフォーマンスモニタリング

- Firebase Analytics で利用状況を分析
- Firebase Crashlytics でクラッシュログを監視

## 重要な注意事項

1.**ファイルベースルーティング**を厳守 - URLとファイルパスを一致させる

2.**認証ガード**は `_layout.tsx` で実装

3.**データフェッチングには TanStack Query** を使用

4.**リスト表示には FlashList** を検討（大量データ時）

5.**画像は expo-image** を使用して最適化
