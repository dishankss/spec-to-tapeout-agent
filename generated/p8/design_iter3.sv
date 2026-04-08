module fp16_multiplier(
  input  logic [15:0] a,
  input  logic [15:0] b,
  output logic [15:0] result
);

  logic        sign_a, sign_b, sign_res;
  logic [4:0]  exp_a, exp_b;
  logic [9:0]  frac_a, frac_b;

  logic        is_zero_a, is_zero_b;
  logic        is_inf_a,  is_inf_b;
  logic        is_nan_a,  is_nan_b;

  logic [10:0] sig_a, sig_b;
  logic [21:0] sig_prod;

  logic [47:0] ext_prod;
  logic [47:0] shifted_val;
  logic [47:0] sticky_mask;

  logic [10:0] mant_pre11;
  logic [10:0] sub_pre11;
  logic [11:0] rounded12;

  logic        guard_bit;
  logic        sticky_bit;
  logic        round_inc;
  logic        found_msb;

  logic [4:0]  exp_field;

  integer exp_a_unb;
  integer exp_b_unb;
  integer exp_sum;
  integer msb_pos;
  integer norm_exp;
  integer shift_amt;
  integer sub_shift;
  integer i;

  always_comb begin
    sign_a    = a[15];
    sign_b    = b[15];
    sign_res  = sign_a ^ sign_b;
    exp_a     = a[14:10];
    exp_b     = b[14:10];
    frac_a    = a[9:0];
    frac_b    = b[9:0];

    is_zero_a = (exp_a == 5'd0)  && (frac_a == 10'd0);
    is_zero_b = (exp_b == 5'd0)  && (frac_b == 10'd0);
    is_inf_a  = (exp_a == 5'd31) && (frac_a == 10'd0);
    is_inf_b  = (exp_b == 5'd31) && (frac_b == 10'd0);
    is_nan_a  = (exp_a == 5'd31) && (frac_a != 10'd0);
    is_nan_b  = (exp_b == 5'd31) && (frac_b != 10'd0);

    sig_a     = 11'd0;
    sig_b     = 11'd0;
    sig_prod  = 22'd0;
    ext_prod  = 48'd0;
    shifted_val = 48'd0;
    sticky_mask = 48'd0;
    mant_pre11  = 11'd0;
    sub_pre11   = 11'd0;
    rounded12   = 12'd0;
    guard_bit   = 1'b0;
    sticky_bit  = 1'b0;
    round_inc   = 1'b0;
    found_msb   = 1'b0;
    exp_field   = 5'd0;

    exp_a_unb = 0;
    exp_b_unb = 0;
    exp_sum   = 0;
    msb_pos   = 0;
    norm_exp  = 0;
    shift_amt = 0;
    sub_shift = 0;

    result = 16'd0;

    if (is_nan_a || is_nan_b || ((is_inf_a || is_inf_b) && (is_zero_a || is_zero_b))) begin
      result = 16'h7E00;
    end else if (is_inf_a || is_inf_b) begin
      result = {sign_res, 5'h1F, 10'd0};
    end else if (is_zero_a || is_zero_b) begin
      result = {sign_res, 5'd0, 10'd0};
    end else begin
      sig_a = (exp_a == 5'd0) ? {1'b0, frac_a} : {1'b1, frac_a};
      sig_b = (exp_b == 5'd0) ? {1'b0, frac_b} : {1'b1, frac_b};

      exp_a_unb = (exp_a == 5'd0) ? -14 : (exp_a - 15);
      exp_b_unb = (exp_b == 5'd0) ? -14 : (exp_b - 15);
      exp_sum   = exp_a_unb + exp_b_unb;

      sig_prod = sig_a * sig_b;
      ext_prod = {26'd0, sig_prod};

      found_msb = 1'b0;
      msb_pos   = 0;
      for (i = 21; i >= 0; i = i - 1) begin
        if (!found_msb && sig_prod[i]) begin
          found_msb = 1'b1;
          msb_pos   = i;
        end
      end

      if (sig_prod == 22'd0) begin
        result = {sign_res, 5'd0, 10'd0};
      end else begin
        norm_exp = exp_sum + msb_pos - 20;

        if (norm_exp > 15) begin
          result = {sign_res, 5'h1F, 10'd0};
        end else if (norm_exp >= -14) begin
          shift_amt = msb_pos - 10;

          if (shift_amt >= 0) begin
            shifted_val = ext_prod >> shift_amt;
            mant_pre11  = shifted_val[10:0];

            if (shift_amt > 0) begin
              guard_bit = ext_prod[shift_amt-1];
              if (shift_amt > 1) begin
                sticky_mask = (48'd1 << (shift_amt - 1)) - 1;
                sticky_bit  = |(ext_prod & sticky_mask);
              end else begin
                sticky_bit = 1'b0;
              end
            end else begin
              guard_bit  = 1'b0;
              sticky_bit = 1'b0;
            end
          end else begin
            shifted_val = ext_prod << (-shift_amt);
            mant_pre11  = shifted_val[10:0];
            guard_bit   = 1'b0;
            sticky_bit  = 1'b0;
          end

          round_inc = guard_bit && (sticky_bit || mant_pre11[0]);
          rounded12 = {1'b0, mant_pre11} + round_inc;

          if (rounded12[11]) begin
            norm_exp  = norm_exp + 1;
            mant_pre11 = 11'd1024;
          end else begin
            mant_pre11 = rounded12[10:0];
          end

          if (norm_exp > 15) begin
            result = {sign_res, 5'h1F, 10'd0};
          end else begin
            exp_field = norm_exp + 15;
            result = {sign_res, exp_field, mant_pre11[9:0]};
          end
        end else begin
          sub_shift = -(exp_sum + 4);

          if (sub_shift >= 0) begin
            shifted_val = ext_prod >> sub_shift;
            sub_pre11   = shifted_val[10:0];

            if (sub_shift > 0) begin
              guard_bit = ext_prod[sub_shift-1];
              if (sub_shift > 1) begin
                sticky_mask = (48'd1 << (sub_shift - 1)) - 1;
                sticky_bit  = |(ext_prod & sticky_mask);
              end else begin
                sticky_bit = 1'b0;
              end
            end else begin
              guard_bit  = 1'b0;
              sticky_bit = 1'b0;
            end
          end else begin
            shifted_val = ext_prod << (-sub_shift);
            sub_pre11   = shifted_val[10:0];
            guard_bit   = 1'b0;
            sticky_bit  = 1'b0;
          end

          round_inc = guard_bit && (sticky_bit || sub_pre11[0]);
          rounded12 = {1'b0, sub_pre11} + round_inc;

          if (rounded12 >= 12'd1024) begin
            result = {sign_res, 5'd1, 10'd0};
          end else begin
            result = {sign_res, 5'd0, rounded12[9:0]};
          end
        end
      end
    end
  end

endmodule
