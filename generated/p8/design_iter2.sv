module fp16_multiplier(
  input  logic [15:0] a,
  input  logic [15:0] b,
  output logic [15:0] result
);

  always_comb begin
    logic        sign_a, sign_b, sign_r;
    logic [4:0]  exp_a, exp_b;
    logic [9:0]  frac_a, frac_b;
    logic        a_is_zero, b_is_zero;
    logic        a_is_inf,  b_is_inf;
    logic        a_is_nan,  b_is_nan;
    logic        a_is_sub,  b_is_sub;

    logic [10:0] sig_a, sig_b;
    logic [21:0] product;

    int signed   exp_a_unb, exp_b_unb;
    int signed   exp_sum;
    int signed   exp_norm;
    int signed   exp_norm_rounded;
    int signed   shift_amt;
    int signed   sub_shift;
    int          msb_idx;
    int          i;

    logic [21:0] mant_main_wide;
    logic [21:0] sub_main_wide;
    logic [11:0] mant_round_sum;
    logic [10:0] mant_final;
    logic [10:0] sub_round_sum;
    logic [4:0]  exp_field;

    logic        guard_bit, round_bit, sticky_bit;
    logic        round_inc;

    sign_a = a[15];
    sign_b = b[15];
    sign_r = sign_a ^ sign_b;

    exp_a  = a[14:10];
    exp_b  = b[14:10];
    frac_a = a[9:0];
    frac_b = b[9:0];

    a_is_zero = (exp_a == 5'd0) && (frac_a == 10'd0);
    b_is_zero = (exp_b == 5'd0) && (frac_b == 10'd0);

    a_is_inf  = (exp_a == 5'h1F) && (frac_a == 10'd0);
    b_is_inf  = (exp_b == 5'h1F) && (frac_b == 10'd0);

    a_is_nan  = (exp_a == 5'h1F) && (frac_a != 10'd0);
    b_is_nan  = (exp_b == 5'h1F) && (frac_b != 10'd0);

    a_is_sub  = (exp_a == 5'd0) && (frac_a != 10'd0);
    b_is_sub  = (exp_b == 5'd0) && (frac_b != 10'd0);

    result = 16'h0000;

    if (a_is_nan || b_is_nan) begin
      result = 16'h7E00;
    end else if ((a_is_inf && b_is_zero) || (b_is_inf && a_is_zero)) begin
      result = 16'h7E00;
    end else if (a_is_inf || b_is_inf) begin
      result = {sign_r, 5'h1F, 10'h000};
    end else if (a_is_zero || b_is_zero) begin
      result = {sign_r, 15'h0000};
    end else begin
      sig_a = (exp_a == 5'd0) ? {1'b0, frac_a} : {1'b1, frac_a};
      sig_b = (exp_b == 5'd0) ? {1'b0, frac_b} : {1'b1, frac_b};

      exp_a_unb = (exp_a == 5'd0) ? -14 : ($signed({1'b0, exp_a}) - 15);
      exp_b_unb = (exp_b == 5'd0) ? -14 : ($signed({1'b0, exp_b}) - 15);
      exp_sum   = exp_a_unb + exp_b_unb;

      product = sig_a * sig_b;

      if (product == 22'd0) begin
        result = {sign_r, 15'h0000};
      end else begin
        msb_idx = 0;
        for (i = 21; i >= 0; i = i - 1) begin
          if (product[i]) begin
            msb_idx = i;
            i = -1;
          end
        end

        exp_norm = exp_sum + msb_idx - 20;

        if (exp_norm > 15) begin
          result = {sign_r, 5'h1F, 10'h000};
        end else if (exp_norm >= -14) begin
          shift_amt = msb_idx - 10;
          mant_main_wide = 22'd0;
          guard_bit = 1'b0;
          round_bit = 1'b0;
          sticky_bit = 1'b0;

          if (shift_amt >= 0) begin
            mant_main_wide = product >> shift_amt;

            if (shift_amt >= 1) begin
              guard_bit = product[shift_amt-1];
            end
            if (shift_amt >= 2) begin
              round_bit = product[shift_amt-2];
            end
            if (shift_amt >= 3) begin
              sticky_bit = 1'b0;
              for (i = 0; i <= shift_amt-3; i = i + 1) begin
                sticky_bit = sticky_bit | product[i];
              end
            end
          end else begin
            mant_main_wide = product << (-shift_amt);
          end

          round_inc = guard_bit & (round_bit | sticky_bit | mant_main_wide[0]);
          mant_round_sum = {1'b0, mant_main_wide[10:0]} + {11'd0, round_inc};

          exp_norm_rounded = exp_norm;
          if (mant_round_sum[11]) begin
            mant_final = 11'd1024;
            exp_norm_rounded = exp_norm + 1;
          end else begin
            mant_final = mant_round_sum[10:0];
          end

          if (exp_norm_rounded > 15) begin
            result = {sign_r, 5'h1F, 10'h000};
          end else begin
            exp_field = exp_norm_rounded + 15;
            result = {sign_r, exp_field, mant_final[9:0]};
          end
        end else begin
          sub_shift = -(exp_sum + 4);
          sub_main_wide = 22'd0;
          guard_bit = 1'b0;
          round_bit = 1'b0;
          sticky_bit = 1'b0;

          if (sub_shift > 0) begin
            sub_main_wide = product >> sub_shift;

            if (sub_shift >= 1) begin
              guard_bit = product[sub_shift-1];
            end
            if (sub_shift >= 2) begin
              round_bit = product[sub_shift-2];
            end
            if (sub_shift >= 3) begin
              sticky_bit = 1'b0;
              for (i = 0; i <= sub_shift-3; i = i + 1) begin
                sticky_bit = sticky_bit | product[i];
              end
            end
          end else begin
            sub_main_wide = product << (-sub_shift);
          end

          round_inc = guard_bit & (round_bit | sticky_bit | sub_main_wide[0]);
          sub_round_sum = sub_main_wide[10:0] + {10'd0, round_inc};

          if (sub_round_sum >= 11'd1024) begin
            result = {sign_r, 5'd1, 10'd0};
          end else if (sub_round_sum == 11'd0) begin
            result = {sign_r, 15'h0000};
          end else begin
            result = {sign_r, 5'd0, sub_round_sum[9:0]};
          end
        end
      end
    end
  end

endmodule
