

# Firebase 実装ルール（Next.js Web App）

## 前提条件

- Node.js 20.x 以上
- Next.js 15.x 以上
- React 19.x 以上

## 技術スタック

| サービス                 | 用途                                   |
| ------------------------ | -------------------------------------- |
| Firebase Authentication  | ユーザー認証（メール、Google）         |
| Cloud Firestore          | ユーザーデータ、お気に入り、履歴の保存 |
| Firebase Storage         | ユーザーの写真保存                     |
| Firebase Analytics       | 利用状況分析                           |

## 実装手順

### 1. Firebase プロジェクトの設定

1. [Firebase Console](https://console.firebase.google.com/) でプロジェクトを作成
2. Web アプリを登録
3. Firebase 設定情報を取得

### 2. 環境変数の設定

`.env.local` に以下を設定:

```
NEXT_PUBLIC_FIREBASE_API_KEY=xxx
NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=xxx
NEXT_PUBLIC_FIREBASE_PROJECT_ID=xxx
NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET=xxx
NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID=xxx
NEXT_PUBLIC_FIREBASE_APP_ID=xxx
```

### 3. Firebase の初期化

`lib/firebase.ts` を作成:

```typescript
import { initializeApp, getApps } from "firebase/app";
import { getAuth } from "firebase/auth";
import { getFirestore } from "firebase/firestore";
import { getStorage } from "firebase/storage";

const firebaseConfig = {
  apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY,
  authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN,
  projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
  storageBucket: process.env.NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: process.env.NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID,
  appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID,
};

// 重複初期化を防ぐ
const app = getApps().length === 0 ? initializeApp(firebaseConfig) : getApps()[0];

export const auth = getAuth(app);
export const db = getFirestore(app);
export const storage = getStorage(app);

export default app;
```

### 4. 認証コンテキストの作成

`contexts/auth-context.tsx` を作成:

```typescript
"use client";

import { createContext, useContext, useEffect, useState, ReactNode } from "react";
import {
  User,
  onAuthStateChanged,
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  signOut as firebaseSignOut,
  GoogleAuthProvider,
  signInWithPopup,
} from "firebase/auth";
import { auth } from "@/lib/firebase";

type AuthContextType = {
  user: User | null;
  isLoading: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  signInWithGoogle: () => Promise<void>;
};

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, (user) => {
      setUser(user);
      setIsLoading(false);
    });

    return unsubscribe;
  }, []);

  const signIn = async (email: string, password: string) => {
    await signInWithEmailAndPassword(auth, email, password);
  };

  const signUp = async (email: string, password: string) => {
    await createUserWithEmailAndPassword(auth, email, password);
  };

  const signOut = async () => {
    await firebaseSignOut(auth);
  };

  const signInWithGoogle = async () => {
    const provider = new GoogleAuthProvider();
    await signInWithPopup(auth, provider);
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
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
```

### 5. ルートレイアウトでの設定

`app/layout.tsx` に AuthProvider を追加:

```typescript
import { AuthProvider } from "@/contexts/auth-context";

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ja">
      <body>
        <AuthProvider>
          {children}
        </AuthProvider>
      </body>
    </html>
  );
}
```

### 6. 認証画面の実装

#### サインイン画面

```typescript
"use client";

import { useState } from "react";
import { useAuth } from "@/contexts/auth-context";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default function SignInPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState("");
  const { signIn } = useAuth();
  const router = useRouter();

  const handleSignIn = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || !password) {
      setError("メールアドレスとパスワードを入力してください");
      return;
    }

    setIsLoading(true);
    setError("");
    try {
      await signIn(email, password);
      router.replace("/");
    } catch (err: any) {
      setError(err.message);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <form onSubmit={handleSignIn} className="mx-auto max-w-sm space-y-4 p-6">
      {error && <p className="text-sm text-destructive">{error}</p>}
      <div className="space-y-2">
        <Label htmlFor="email">メールアドレス</Label>
        <Input
          id="email"
          type="email"
          placeholder="mail@example.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="password">パスワード</Label>
        <Input
          id="password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </div>
      <Button type="submit" className="w-full" disabled={isLoading}>
        {isLoading ? "サインイン中..." : "サインイン"}
      </Button>
    </form>
  );
}
```

### 7. Google サインインの実装

```typescript
"use client";

import { useAuth } from "@/contexts/auth-context";
import { Button } from "@/components/ui/button";

export function GoogleSignInButton() {
  const { signInWithGoogle } = useAuth();

  const handleGoogleSignIn = async () => {
    try {
      await signInWithGoogle();
    } catch (error: any) {
      console.error("Google Sign In Error:", error);
    }
  };

  return (
    <Button variant="outline" onClick={handleGoogleSignIn} className="w-full">
      Googleでサインイン
    </Button>
  );
}
```

### 8. 認証ガードの実装

```typescript
"use client";

import { useAuth } from "@/contexts/auth-context";
import { redirect } from "next/navigation";
import { Loader2 } from "lucide-react";

export function AuthGuard({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin" />
      </div>
    );
  }

  if (!user) {
    redirect("/sign-in");
  }

  return <>{children}</>;
}
```

## Firestore セキュリティルール

```javascript
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    // ユーザーデータ
    match /users/{userId} {
      allow read, write: if request.auth != null && request.auth.uid == userId;
    }

    // お気に入り
    match /users/{userId}/favorites/{docId} {
      allow read, write: if request.auth != null && request.auth.uid == userId;
    }

    // 履歴
    match /users/{userId}/history/{docId} {
      allow read, write: if request.auth != null && request.auth.uid == userId;
    }
  }
}
```

## Storage セキュリティルール

```javascript
rules_version = '2';
service firebase.storage {
  match /b/{bucket}/o {
    // ユーザーの写真
    match /users/{userId}/{allPaths=**} {
      allow read, write: if request.auth != null && request.auth.uid == userId;
    }
  }
}
```

## セキュリティルール

1. Firebase設定ファイルは `.gitignore`に追加し、Git にコミットしない
2. 環境変数は `NEXT_PUBLIC_`プレフィックスを使用（公開用）
3. サーバーサイドのみで使用する変数は `NEXT_PUBLIC_` なしで設定
4. Firestoreセキュリティルールを必ず設定
5. Storageセキュリティルールを必ず設定
6. ユーザー入力は必ずバリデーションを行う

## エラーハンドリング

1. 認証エラーは適切にキャッチしてユーザーフレンドリーなメッセージを表示
2. ネットワークエラーは適切にハンドリング
3. ローディング状態は必ず表示

## 重要事項

1.**AuthContext**と**AuthGuard**の実装は遵守してください

2. Google サインインには Firebase Console でプロバイダを有効化し、認証ドメインを設定してください
3. 開発時は Firebase Emulator の使用を推奨します
