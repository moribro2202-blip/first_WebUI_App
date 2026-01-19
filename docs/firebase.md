

# Firebase Authentication 実装ルール（React Native/Expo）

## 前提条件

- Node.js 18.x 以上
- Expo SDK 52.x 以上
- React Native 0.76.x 以上

## 技術スタック

| サービス                 | 用途                                   |

| ------------------------ | -------------------------------------- |

| Firebase Authentication  | ユーザー認証（メール、Apple、Google）  |

| Cloud Firestore          | ユーザーデータ、お気に入り、履歴の保存 |

| Firebase Storage         | ユーザーの写真保存                     |

| Firebase Cloud Messaging | プッシュ通知                           |

| Firebase Analytics       | 利用状況分析                           |

## 実装手順

### 1. Firebase プロジェクトの設定

1. [Firebase Console](https://console.firebase.google.com/) でプロジェクトを作成
2. iOS/Android アプリを登録
3. 設定ファイルをダウンロード

   - iOS: `GoogleService-Info.plist`
   - Android: `google-services.json`

### 2. 環境変数の設定

`app.config.js` または `.env` ファイルに以下を設定：

```javascript

// app.config.js

exportdefault {

  expo: {

    // ...

    extra: {

      firebaseApiKey: process.env.FIREBASE_API_KEY,

      firebaseAuthDomain: process.env.FIREBASE_AUTH_DOMAIN,

      firebaseProjectId: process.env.FIREBASE_PROJECT_ID,

      firebaseStorageBucket: process.env.FIREBASE_STORAGE_BUCKET,

      firebaseMessagingSenderId: process.env.FIREBASE_MESSAGING_SENDER_ID,

      firebaseAppId: process.env.FIREBASE_APP_ID,

    },

  },

};

```

### 3. Firebase の初期化

`lib/firebase.ts` を作成：

```typescript

import { initializeApp, getApps } from"firebase/app";

import { initializeAuth, getReactNativePersistence } from"firebase/auth";

import { getFirestore } from"firebase/firestore";

import { getStorage } from"firebase/storage";

import AsyncStorage from"@react-native-async-storage/async-storage";


const firebaseConfig = {

  apiKey: process.env.EXPO_PUBLIC_FIREBASE_API_KEY,

  authDomain: process.env.EXPO_PUBLIC_FIREBASE_AUTH_DOMAIN,

  projectId: process.env.EXPO_PUBLIC_FIREBASE_PROJECT_ID,

  storageBucket: process.env.EXPO_PUBLIC_FIREBASE_STORAGE_BUCKET,

  messagingSenderId: process.env.EXPO_PUBLIC_FIREBASE_MESSAGING_SENDER_ID,

  appId: process.env.EXPO_PUBLIC_FIREBASE_APP_ID,

};


// 重複初期化を防ぐ

const app =getApps().length ===0?initializeApp(firebaseConfig) :getApps()[0];


// React Native用の永続化設定

exportconst auth =initializeAuth(app, {

  persistence: getReactNativePersistence(AsyncStorage),

});


exportconst db =getFirestore(app);

exportconst storage =getStorage(app);


exportdefault app;

```

### 4. 認証コンテキストの作成

`contexts/AuthContext.tsx` を作成：

```typescript

import { createContext, useContext, useEffect, useState, ReactNode } from"react";

import {

  User,

  onAuthStateChanged,

  signInWithEmailAndPassword,

  createUserWithEmailAndPassword,

  signOut as firebaseSignOut,

  GoogleAuthProvider,

  signInWithCredential,

  OAuthProvider,

} from"firebase/auth";

import { auth } from"@/lib/firebase";


typeAuthContextType= {

  user:User|null;

  isLoading:boolean;

  signIn: (email:string, password:string) =>Promise<void>;

  signUp: (email:string, password:string) =>Promise<void>;

  signOut: () =>Promise<void>;

  signInWithGoogle: (idToken:string) =>Promise<void>;

  signInWithApple: (identityToken:string, nonce:string) =>Promise<void>;

};


const AuthContext =createContext<AuthContextType|undefined>(undefined);


exportfunctionAuthProvider({ children }: { children:ReactNode }) {

  const [user, setUser] =useState<User|null>(null);

  const [isLoading, setIsLoading] =useState(true);


  useEffect(() => {

    const unsubscribe =onAuthStateChanged(auth, (user) => {

      setUser(user);

      setIsLoading(false);

    });


    return unsubscribe;

  }, []);


  constsignIn=async (email:string, password:string) => {

    awaitsignInWithEmailAndPassword(auth, email, password);

  };


  constsignUp=async (email:string, password:string) => {

    awaitcreateUserWithEmailAndPassword(auth, email, password);

  };


  constsignOut=async () => {

    awaitfirebaseSignOut(auth);

  };


  constsignInWithGoogle=async (idToken:string) => {

    const credential = GoogleAuthProvider.credential(idToken);

    awaitsignInWithCredential(auth, credential);

  };


  constsignInWithApple=async (identityToken:string, nonce:string) => {

    const provider =newOAuthProvider("apple.com");

    const credential = provider.credential({

      idToken: identityToken,

      rawNonce: nonce,

    });

    awaitsignInWithCredential(auth, credential);

  };


  return (

    <AuthContext.Provider

      value={{

        user,

        isLoading,

        signIn,

        signUp,

        signOut,

        signInWithGoogle,

        signInWithApple,

      }}

    >

      {children}

    </AuthContext.Provider>

  );

}


exportfunctionuseAuth() {

  const context =useContext(AuthContext);

  if (context ===undefined) {

    thrownewError("useAuth must be used within an AuthProvider");

  }

  return context;

}

```

### 5. ルートレイアウトでの設定

`app/_layout.tsx` に AuthProvider を追加：

```typescript

import { Stack } from"expo-router";

import { AuthProvider } from"@/contexts/AuthContext";


exportdefaultfunctionRootLayout() {

  return (

    <AuthProvider>

      <Stack>

        <Stack.Screen name="(tabs)" options={{ headerShown: false }} />

        <Stack.Screen name="(auth)" options={{ headerShown: false }} />

      </Stack>

    </AuthProvider>

  );

}

```

### 6. 認証画面の実装

#### サインイン画面

```typescript

import { useState } from"react";

import { View, TextInput, TouchableOpacity, Text, Alert } from"react-native";

import { useAuth } from"@/contexts/AuthContext";

import { router } from"expo-router";


exportdefaultfunctionSignInScreen() {

  const [email, setEmail] =useState("");

  const [password, setPassword] =useState("");

  const [isLoading, setIsLoading] =useState(false);

  const { signIn } =useAuth();


  consthandleSignIn=async () => {

    if (!email ||!password) {

      Alert.alert("エラー", "メールアドレスとパスワードを入力してください");

      return;

    }


    setIsLoading(true);

    try {

      awaitsignIn(email, password);

      router.replace("/(tabs)");

    } catch (error:any) {

      Alert.alert("エラー", error.message);

    } finally {

      setIsLoading(false);

    }

  };


  return (

    <View>

      <TextInput

        placeholder="メールアドレス"

        value={email}

        onChangeText={setEmail}

        keyboardType="email-address"

        autoCapitalize="none"

      />

      <TextInput

        placeholder="パスワード"

        value={password}

        onChangeText={setPassword}

        secureTextEntry

      />

      <TouchableOpacity onPress={handleSignIn} disabled={isLoading}>

        <Text>{isLoading ? "サインイン中..." : "サインイン"}</Text>

      </TouchableOpacity>

    </View>

  );

}

```

### 7. Google サインインの実装

```typescript

import { useEffect } from"react";

import*as Google from"expo-auth-session/providers/google";

import { useAuth } from"@/contexts/AuthContext";


exportfunctionuseGoogleSignIn() {

  const { signInWithGoogle } =useAuth();


  const [request, response, promptAsync] = Google.useIdTokenAuthRequest({

    clientId: process.env.EXPO_PUBLIC_GOOGLE_CLIENT_ID,

    iosClientId: process.env.EXPO_PUBLIC_GOOGLE_IOS_CLIENT_ID,

    androidClientId: process.env.EXPO_PUBLIC_GOOGLE_ANDROID_CLIENT_ID,

  });


  useEffect(() => {

    if (response?.type ==="success") {

      const { id_token } = response.params;

      signInWithGoogle(id_token);

    }

  }, [response]);


  return { promptAsync, isLoading: !request };

}

```

### 8. Apple サインインの実装

```typescript

import*as AppleAuthentication from"expo-apple-authentication";

import*as Crypto from"expo-crypto";

import { useAuth } from"@/contexts/AuthContext";


exportfunctionuseAppleSignIn() {

  const { signInWithApple } =useAuth();


  consthandleAppleSignIn=async () => {

    try {

      const nonce = Math.random().toString(36).substring(2, 10);

      const hashedNonce =await Crypto.digestStringAsync(

        Crypto.CryptoDigestAlgorithm.SHA256,

        nonce

      );


      const credential =await AppleAuthentication.signInAsync({

        requestedScopes: [

          AppleAuthentication.AppleAuthenticationScope.FULL_NAME,

          AppleAuthentication.AppleAuthenticationScope.EMAIL,

        ],

        nonce: hashedNonce,

      });


      if (credential.identityToken) {

        awaitsignInWithApple(credential.identityToken, nonce);

      }

    } catch (error:any) {

      if (error.code !=="ERR_CANCELED") {

        console.error("Apple Sign In Error:", error);

      }

    }

  };


  return { handleAppleSignIn };

}

```

### 9. 認証ガードの実装

```typescript

import { useAuth } from"@/contexts/AuthContext";

import { Redirect } from"expo-router";

import { ActivityIndicator, View } from"react-native";


exportfunctionAuthGuard({ children }: { children:React.ReactNode }) {

  const { user, isLoading } =useAuth();


  if (isLoading) {

    return (

      <View style={{ flex: 1, justifyContent: "center", alignItems: "center" }}>

        <ActivityIndicator size="large"/>

      </View>

    );

  }


  if (!user) {

    return <Redirecthref="/(auth)/sign-in" />;

  }


  return <>{children}</>;

}

```

## Firestore セキュリティルール

```javascript

rules_version ='2';

service cloud.firestore {

  match /databases/{database}/documents {

    // ユーザーデータ

    match /users/{userId} {

      allow read, write: if request.auth !=null&& request.auth.uid == userId;

    }


    // お気に入り

    match /users/{userId}/favorites/{docId} {

      allow read, write: if request.auth !=null&& request.auth.uid == userId;

    }


    // 履歴

    match /users/{userId}/history/{docId} {

      allow read, write: if request.auth !=null&& request.auth.uid == userId;

    }

  }

}

```

## Storage セキュリティルール

```javascript

rules_version ='2';

service firebase.storage {

  match /b/{bucket}/o {

    // ユーザーの写真

    match /users/{userId}/{allPaths=**} {

      allow read, write: if request.auth !=null&& request.auth.uid == userId;

    }

  }

}

```

## セキュリティルール

1. Firebase設定ファイルは `.gitignore`に追加し、Git にコミットしない
2. 環境変数は `EXPO_PUBLIC_`プレフィックスを使用（公開用）
3. Firestoreセキュリティルールを必ず設定
4. Storageセキュリティルールを必ず設定
5. ユーザー入力は必ずバリデーションを行う

## エラーハンドリング

1. 認証エラーは適切にキャッチしてユーザーフレンドリーなメッセージを表示
2. ネットワークエラーは適切にハンドリング
3. ローディング状態は必ず表示
4. オフライン時の挙動を考慮

## パフォーマンス最適化

1.`AsyncStorage`による認証状態の永続化

2. 不要な認証チェックは避ける
3. コンポーネントの分割を適切に行い、認証状態の変更による再レンダリングを最小限に
4. Firestoreのオフライン永続化を活用

## 重要事項

1.**AuthContext**と**AuthGuard**の実装は遵守してください

2. Google/Appleサインインには追加のネイティブ設定が必要です
3. 実機テストを必ず行ってください
4. Firebase Console で認証プロバイダー（Email、Google、Apple）を有効化してください
