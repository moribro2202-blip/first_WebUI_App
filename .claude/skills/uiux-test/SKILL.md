---
name: uiux-test
description: Next.js/ReactのUI/UXテスト作成ガイド。コンポーネントテスト、スナップショットテスト、アクセシビリティテスト、インタラクションテストのベストプラクティスを提供。UIテスト、コンポーネントテスト作成時に使用。
---

# UI/UX テスト ベストプラクティス

Next.js / React プロジェクトにおけるUI/UXテストのガイド。

## When to Use This Skill

- UIコンポーネントのテストを作成する時
- スナップショットテストを追加する時
- アクセシビリティテストを書く時
- ユーザーインタラクションのテストを書く時

## テストファイル配置

```
src/
├── components/
│   ├── ui/
│   │   ├── button.tsx
│   │   └── __tests__/
│   │       └── button.test.tsx
│   └── features/
│       ├── auth/
│       │   ├── login-form.tsx
│       │   └── __tests__/
│       │       └── login-form.test.tsx
```

## 基本構造

```typescript
import { render, screen, fireEvent } from "@testing-library/react";
import { Button } from "../button";

describe("Button", () => {
  // レンダリングテスト
  it("renders correctly with label", () => {
    render(<Button>送信</Button>);
    expect(screen.getByText("送信")).toBeInTheDocument();
  });

  // インタラクションテスト
  it("calls onClick when clicked", () => {
    const onClickMock = vi.fn();
    render(<Button onClick={onClickMock}>送信</Button>);

    fireEvent.click(screen.getByText("送信"));

    expect(onClickMock).toHaveBeenCalledTimes(1);
  });

  // 状態テスト
  it("is disabled when disabled prop is true", () => {
    render(<Button disabled>送信</Button>);

    expect(screen.getByText("送信")).toBeDisabled();
  });
});
```

## アクセシビリティテスト

```typescript
describe("Button accessibility", () => {
  it("has correct aria-label", () => {
    render(
      <Button aria-label="フォームを送信">送信</Button>
    );

    expect(screen.getByLabelText("フォームを送信")).toBeInTheDocument();
  });

  it("has correct role", () => {
    render(<Button>送信</Button>);

    expect(screen.getByRole("button")).toBeInTheDocument();
  });

  it("announces disabled state", () => {
    render(<Button disabled>送信</Button>);

    expect(screen.getByRole("button")).toBeDisabled();
  });
});
```

## フォームテスト

```typescript
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LoginForm } from "../login-form";

describe("LoginForm", () => {
  it("shows validation error for empty email", async () => {
    render(<LoginForm onSubmit={() => {}} />);

    await userEvent.click(screen.getByText("ログイン"));

    await waitFor(() => {
      expect(screen.getByText("メールアドレスを入力してください")).toBeInTheDocument();
    });
  });

  it("submits form with valid data", async () => {
    const onSubmitMock = vi.fn();
    render(<LoginForm onSubmit={onSubmitMock} />);

    await userEvent.type(
      screen.getByLabelText("メールアドレス"),
      "test@example.com"
    );
    await userEvent.type(
      screen.getByLabelText("パスワード"),
      "password123"
    );
    await userEvent.click(screen.getByText("ログイン"));

    await waitFor(() => {
      expect(onSubmitMock).toHaveBeenCalledWith({
        email: "test@example.com",
        password: "password123",
      });
    });
  });
});
```

## ローディング状態テスト

```typescript
describe("Button loading state", () => {
  it("shows loading indicator when loading", () => {
    render(<Button isLoading>送信</Button>);

    expect(screen.getByTestId("loading-spinner")).toBeInTheDocument();
  });

  it("disables interaction when loading", () => {
    const onClickMock = vi.fn();
    render(<Button isLoading onClick={onClickMock}>送信</Button>);

    fireEvent.click(screen.getByRole("button"));

    expect(onClickMock).not.toHaveBeenCalled();
  });
});
```

## モック設定

### Next.js ナビゲーションモック

```typescript
// vitest.setup.ts
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
  }),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
}));
```

### next/image モック

```typescript
vi.mock("next/image", () => ({
  default: (props: any) => <img {...props} />,
}));
```

## AI Assistant Instructions

テスト作成時は以下を遵守:

1. **必ず実際の機能を検証する** - `expect(true).toBe(true)` は禁止
2. **ユーザー視点でテストを書く** - 実装詳細ではなく振る舞いをテスト
3. **アクセシビリティを検証** - aria-label, role を確認
4. **境界値・異常系をテスト** - 空データ、無効な入力、エラー状態
5. **テストIDよりテキスト/ロールを優先** - `getByText`, `getByRole` を使用

### テスト命名規則

```typescript
// Good: 振る舞いを説明
it("shows error message when email is invalid", () => {});
it("navigates to profile page when avatar is clicked", () => {});

// Bad: 実装詳細
it("sets isError to true", () => {});
it("calls handleClick function", () => {});
```

### カバレッジ目標

- UIコンポーネント: 80%以上
- フォームコンポーネント: 90%以上（バリデーション含む）
- 重要なユーザーフロー: 100%
