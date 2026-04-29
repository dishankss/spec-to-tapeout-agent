module fp16_multiplier(
  input  logic [15:0] a,
  input  logic [15:0] b,
  output logic [15:0] result
);

  logic        sign_a;
  logic        sign_b;
  logic        sign_r;
  logic [4:0]  exp_a;
  logic [4:0]  exp_b;
  logic [9:0]  frac_a;
  logic [9:0]  frac_b;
  logic        a_is_zero;
  logic        b_is_zero;
  logic        a_is_inf;
  logic        b_is_inf;
  logic        a_is_nan;
  logic        b_is_nan;
  logic [10:0] mant_a;
  logic [10:0] mant_b;
  logic [21:0] mant_prod;
  logic [10:0] mant_norm;
  logic [10:0] mant_rounded;
  logic [9:0]  frac_out;
  logic [4:0]  exp_out;
  logic        guard_bit;
  logic        sticky_bit;
  logic        round_up;
  logic        round_carry;
  logic [10:0] sub_trunc;
  logic [10:0] sub_round;
  integer      exp_a_unbias;
  integer      exp_b_unbias;
  integer      exp_sum;
  integer      exp_norm;
  integer      shift_sub;
  integer      i;

  always @(*) begin
    sign_a       = 1'b0;
    sign_b       = 1'b0;
    sign_r       = 1'b0;
    exp_a        = 5'd0;
    exp_b        = 5'd0;
    frac_a       = 10'd0;
    frac_b       = 10'd0;
    a_is_zero    = 1'b0;
    b_is_zero    = 1'b0;
    a_is_inf     = 1'b0;
    b_is_inf     = 1'b0;
    a_is_nan     = 1'b0;
    b_is_nan     = 1'b0;
    mant_a       = 11'd0;
    mant_b       = 11'd0;
    mant_prod    = 22'd0;
    mant_norm    = 11'd0;
    mant_rounded = 11'd0;
    frac_out     = 10'd0;
    exp_out      = 5'd0;
    guard_bit    = 1'b0;
    sticky_bit   = 1'b0;
    round_up     = 1'b0;
    round_carry  = 1'b0;
    sub_trunc    = 11'd0;
    sub_round    = 11'd0;
    exp_a_unbias = 0;
    exp_b_unbias = 0;
    exp_sum      = 0;
    exp_norm     = 0;
    shift_sub    = 0;
    result       = 16'd0;

    sign_a    = a[15];
    sign_b    = b[15];
    sign_r    = sign_a ^ sign_b;
    exp_a     = a[14:10];
    exp_b     = b[14:10];
    frac_a    = a[9:0];
    frac_b    = b[9:0];

    a_is_zero = (exp_a == 5'd0) && (frac_a == 10'd0);
    b_is_zero = (exp_b == 5'd0) && (frac_b == 10'd0);
    a_is_inf  = (exp_a == 5'd31) && (frac_a == 10'd0);
    b_is_inf  = (exp_b == 5'd31) && (frac_b == 10'd0);
    a_is_nan  = (exp_a == 5'd31) && (frac_a != 10'd0);
    b_is_nan  = (exp_b == 5'd31) && (frac_b != 10'd0);

    if (a_is_nan || b_is_nan) begin
      result = 16'h7E00;
    end else if ((a_is_inf && b_is_zero) || (b_is_inf && a_is_zero)) begin
      result = 16'h7E00;
    end else if (a_is_inf || b_is_inf) begin
      result = {sign_r, 5'h1F, 10'd0};
    end else if (a_is_zero || b_is_zero) begin
      result = {sign_r, 5'd0, 10'd0};
    end else begin
      if (exp_a == 5'd0) begin
        exp_a_unbias = -14;
        mant_a       = {1'b0, frac_a};
      end else begin
        exp_a_unbias = $signed({1'b0, exp_a}) - 15;
        mant_a       = {1'b1, frac_a};
      end

      if (exp_b == 5'd0) begin
        exp_b_unbias = -14;
        mant_b       = {1'b0, frac_b};
      end else begin
        exp_b_unbias = $signed({1'b0, exp_b}) - 15;
        mant_b       = {1'b1, frac_b};
      end

      mant_prod = mant_a * mant_b;
      exp_sum   = exp_a_unbias + exp_b_unbias;

      if (mant_prod[21]) begin
        mant_norm  = mant_prod[21:11];
        guard_bit  = mant_prod[10];
        sticky_bit = |mant_prod[9:0];
        exp_norm   = exp_sum + 1;
      end else begin
        mant_norm  = mant_prod[20:10];
        guard_bit  = mant_prod[9];
        sticky_bit = |mant_prod[8:0];
        exp_norm   = exp_sum;
      end

      round_up     = guard_bit && (sticky_bit || mant_norm[0]);
      mant_rounded = mant_norm + {{10{1'b0}}, round_up};
      round_carry  = 1'b0;

      if (mant_rounded[10:0] == 11'd2048) begin
        mant_rounded = 11'd1024;
        round_carry  = 1'b1;
      end

      exp_norm = exp_norm + (round_carry ? 1 : 0);

      if (exp_norm > 15) begin
        result = {sign_r, 5'h1F, 10'd0};
      end else if (exp_norm >= -14) begin
        exp_out  = exp_norm + 15;
        frac_out = mant_rounded[9:0];
        result   = {sign_r, exp_out, frac_out};
      end else begin
        shift_sub = -14 - exp_norm;
        sub_trunc = 11'd0;
        sub_round = 11'd0;
        guard_bit = 1'b0;
        sticky_bit = 1'b0;
        round_up = 1'b0;

        if (shift_sub >= 25) begin
          sub_trunc  = 11'd0;
          guard_bit  = 1'b0;
          sticky_bit = (mant_rounded != 11'd0);
        end else begin
          sub_trunc = mant_rounded >> shift_sub;

          if (shift_sub > 0) begin
            guard_bit = mant_rounded[shift_sub-1];
          end else begin
            guard_bit = 1'b0;
          end

          sticky_bit = 1'b0;
          for (i = 0; i < 11; i = i + 1) begin
            if (i < (shift_sub - 1)) begin
              sticky_bit = sticky_bit | mant_rounded[i];
            end
          end
        end

        round_up  = guard_bit && (sticky_bit || sub_trunc[0]);
        sub_round = sub_trunc + {{10{1'b0}}, round_up};

        if (sub_round >= 11'd1024) begin
          result = {sign_r, 5'd1, 10'd0};
        end else begin
          result = {sign_r, 5'd0, sub_round[9:0]};
        end
      end
    end
  end

endmodule
