module seq_detector_0011(
    input clk,
    input reset,
    input data_in,
    output reg detected
);

reg [3:0] shift_reg;
reg [3:0] next_shift;

always @(posedge clk) begin
    if (reset) begin
        shift_reg <= 4'b0000;
        detected <= 1'b0;
    end else begin
        next_shift = {shift_reg[2:0], data_in};
        shift_reg <= next_shift;
        if (next_shift == 4'b0011) begin
            detected <= 1'b1;
        end else begin
            detected <= 1'b0;
        end
    end
end

endmodule
